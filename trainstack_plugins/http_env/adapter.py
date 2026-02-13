import os
from typing import TYPE_CHECKING, Any

from slime.utils.http_utils import post

if TYPE_CHECKING:
    from slime.utils.types import Sample

_TOKENIZER = None


class _FallbackTokenizer:
    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        del add_special_tokens
        return [ord(ch) for ch in text]


def _get_tokenizer(args):
    global _TOKENIZER
    if _TOKENIZER is None:
        try:
            from slime.utils.processing_utils import load_tokenizer

            _TOKENIZER = load_tokenizer(args.hf_checkpoint, trust_remote_code=True)
        except Exception:
            _TOKENIZER = _FallbackTokenizer()
    return _TOKENIZER


def _prompt_to_text(prompt: str | list[dict[str, Any]]) -> str:
    if isinstance(prompt, str):
        return prompt
    if isinstance(prompt, list):
        lines = []
        for msg in prompt:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")
        return "\n".join(lines)
    return str(prompt)


def _reward_from_label(action_text: str, label: Any) -> float:
    if label is None:
        return 0.0
    if isinstance(label, dict):
        expected = str(label.get("answer", label.get("ground_truth", ""))).strip()
    else:
        expected = str(label).strip()
    if not expected:
        return 0.0
    return 1.0 if action_text.strip().lower() == expected.lower() else 0.0


async def generate(args, sample: "Sample", sampling_params: dict[str, Any], evaluation: bool = False) -> "Sample":
    """Custom generate function that talks to an external HTTP environment service."""
    del evaluation
    if args.partial_rollout:
        raise RuntimeError("partial_rollout is not supported in trainstack_plugins.http_env.adapter.generate")

    tokenizer = _get_tokenizer(args)
    prompt_text = _prompt_to_text(sample.prompt)
    prompt_token_ids = tokenizer.encode(prompt_text, add_special_tokens=False)

    env_base = os.getenv("TRAINSTACK_HTTP_ENV_URL", "http://127.0.0.1:18080").rstrip("/")
    llm_url = os.getenv("TRAINSTACK_LLM_URL", f"http://{args.sglang_router_ip}:{args.sglang_router_port}/generate")
    max_turns = int(os.getenv("TRAINSTACK_HTTP_ENV_MAX_TURNS", "8"))

    response_parts: list[str] = []
    response_token_ids: list[int] = []
    loss_mask: list[int] = []
    rollout_log_probs: list[float] = []
    generated_token_budget = int(sampling_params.get("max_new_tokens", args.rollout_max_response_len))
    generated_token_count = 0

    session_id = None
    last_reward = sample.reward
    finish_reason = "stop"

    try:
        start_resp = await post(
            f"{env_base}/v1/session/start",
            {
                "task": {
                    "prompt": prompt_text,
                    "label": sample.label,
                    "metadata": sample.metadata or {},
                }
            },
        )
        session_id = start_resp["session_id"]
        done = bool(start_resp.get("done", False))
        if start_resp.get("reward") is not None:
            last_reward = float(start_resp["reward"])

        init_obs = start_resp.get("observation")
        if init_obs:
            obs_text = str(init_obs)
            obs_ids = tokenizer.encode(obs_text, add_special_tokens=False)
            response_parts.append(obs_text)
            response_token_ids.extend(obs_ids)
            loss_mask.extend([0] * len(obs_ids))
            rollout_log_probs.extend([0.0] * len(obs_ids))

        turn = 0
        while not done and turn < max_turns:
            turn += 1
            remaining = generated_token_budget - generated_token_count
            if remaining <= 0:
                finish_reason = "length"
                break

            req_sampling_params = dict(sampling_params)
            req_sampling_params["max_new_tokens"] = remaining

            gen_output = await post(
                llm_url,
                {
                    "text": prompt_text + "".join(response_parts),
                    "sampling_params": req_sampling_params,
                    "return_logprob": True,
                },
            )

            meta_info = gen_output.get("meta_info", {})
            finish_type = meta_info.get("finish_reason", {}).get("type", "stop")
            action_text = gen_output.get("text", "")

            if finish_type == "abort":
                sample.status = type(sample).Status.ABORTED
                sample.reward = 0.0 if last_reward is None else float(last_reward)
                return sample

            output_token_logprobs = meta_info.get("output_token_logprobs") or []
            if output_token_logprobs:
                action_token_ids = [item[1] for item in output_token_logprobs]
                action_log_probs = [float(item[0]) for item in output_token_logprobs]
            else:
                action_token_ids = tokenizer.encode(action_text, add_special_tokens=False)
                action_log_probs = [0.0] * len(action_token_ids)

            generated_token_count += len(action_token_ids)
            response_parts.append(action_text)
            response_token_ids.extend(action_token_ids)
            loss_mask.extend([1] * len(action_token_ids))
            rollout_log_probs.extend(action_log_probs)

            if finish_type == "length":
                finish_reason = "length"
                break

            step_resp = await post(
                f"{env_base}/v1/session/step",
                {
                    "session_id": session_id,
                    "action": action_text,
                },
            )
            done = bool(step_resp.get("done", False))
            if step_resp.get("reward") is not None:
                last_reward = float(step_resp["reward"])

            obs = step_resp.get("observation")
            if obs:
                obs_text = str(obs)
                obs_ids = tokenizer.encode(obs_text, add_special_tokens=False)
                response_parts.append(obs_text)
                response_token_ids.extend(obs_ids)
                loss_mask.extend([0] * len(obs_ids))
                rollout_log_probs.extend([0.0] * len(obs_ids))

        if turn >= max_turns and not done:
            finish_reason = "length"

        if last_reward is None:
            last_reward = _reward_from_label("".join(response_parts), sample.label)

        sample.tokens = prompt_token_ids + response_token_ids
        sample.response = "".join(response_parts)
        sample.response_length = len(response_token_ids)
        sample.loss_mask = loss_mask
        sample.rollout_log_probs = rollout_log_probs if rollout_log_probs else None
        sample.reward = float(last_reward)
        if finish_reason == "length":
            sample.status = type(sample).Status.TRUNCATED
        else:
            sample.status = type(sample).Status.COMPLETED
        sample.metadata = sample.metadata or {}
        sample.metadata["http_env_session_id"] = session_id
    except Exception as exc:
        sample.status = type(sample).Status.FAILED
        sample.reward = 0.0 if last_reward is None else float(last_reward)
        sample.metadata = sample.metadata or {}
        sample.metadata["http_env_error"] = str(exc)
    finally:
        if session_id is not None:
            try:
                await post(f"{env_base}/v1/session/close", {"session_id": session_id})
            except Exception:
                pass

    return sample
