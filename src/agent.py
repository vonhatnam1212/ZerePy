import json
import logging
import time
from pathlib import Path
from typing import Optional, Any
import src.actions.twitter_actions
import src.actions.supabase_actions
from src.action_handler import execute_action
from src.connection_manager import ConnectionManager
from src.helpers import print_h_bar

REQUIRED_FIELDS = ["name", "bio", "traits",
                   "examples", "loop_delay", "config", "tasks"]

logger = logging.getLogger("agent")


class ZerePyAgent:
    def __init__(
            self,
            agent_name: str
    ):
        try:
            agent_path = Path("agents") / f"{agent_name}.json"
            agent_dict = json.load(open(agent_path, "r"))

            missing_fields = [
                field for field in REQUIRED_FIELDS if field not in agent_dict]
            if missing_fields:
                raise KeyError(
                    f"Missing required fields: {', '.join(missing_fields)}")

            self.name = agent_dict["name"]
            self.bio = agent_dict["bio"]
            self.traits = agent_dict["traits"]
            self.examples = agent_dict["examples"]
            self.loop_delay = agent_dict["loop_delay"]
            self.connection_manager = ConnectionManager(agent_dict["config"])
            self.use_time_based_weights = agent_dict["use_time_based_weights"]
            self.time_based_multipliers = agent_dict["time_based_multipliers"]
            self.is_llm_set = False

            # Cache for system prompt
            self._system_prompt = None

            # Extract loop tasks
            self.tasks = agent_dict.get("tasks", [])
            self.task_weights = [task.get("weight", 0) for task in self.tasks]
            self.logger = logging.getLogger("agent")

            # Set up empty agent state
            self.state = {}
        except Exception as e:
            logger.error("Could not load ZerePy agent")
            raise e

    def _setup_llm_provider(self):
        # Get first available LLM provider and its model
        llm_providers = self.connection_manager.get_model_providers()
        if not llm_providers:
            raise ValueError("No configured LLM provider found")
        self.model_provider = llm_providers[0]

    def _construct_system_prompt(self) -> str:
        """Construct the system prompt from agent configuration"""
        if self._system_prompt is None:
            prompt_parts = []
            prompt_parts.extend(self.bio)

            if self.traits:
                prompt_parts.append("\nYour key traits are:")
                prompt_parts.extend(f"- {trait}" for trait in self.traits)

            if self.examples:
                prompt_parts.append(
                    "\nHere are some examples of your style (Please avoid repeating any of these):")
                if self.examples:
                    prompt_parts.extend(
                        f"- {example}" for example in self.examples)

            self._system_prompt = "\n".join(prompt_parts)

        return self._system_prompt

    def _adjust_weights_for_time(self, current_hour: int, task_weights: list) -> list:
        weights = task_weights.copy()

        # Reduce tweet frequency during night hours (1 AM - 5 AM)
        if 1 <= current_hour <= 5:
            weights = [
                weight * self.time_based_multipliers.get("tweet_night_multiplier", 0.4) if task["name"] == "post-tweet"
                else weight
                for weight, task in zip(weights, self.tasks)
            ]

        # Increase engagement frequency during day hours (8 AM - 8 PM) (peak hours?🤔)
        if 8 <= current_hour <= 20:
            weights = [
                weight * self.time_based_multipliers.get("engagement_day_multiplier", 1.5) if task["name"] in (
                    "reply-to-tweet", "like-tweet")
                else weight
                for weight, task in zip(weights, self.tasks)
            ]

        return weights

    def prompt_llm(
            self,
            prompt: str,
            system_prompt: str = None,
            stop: Optional[list[str]] = None,
            response_format: Optional[Any] = None
    ) -> str:
        if not self.is_llm_set:
            self._setup_llm_provider()
        """Generate text using the configured LLM provider"""
        system_prompt = system_prompt or self._construct_system_prompt()

        return self.connection_manager.perform_action(
            connection_name=self.model_provider,
            action_name="generate-text",
            params=[prompt, system_prompt, stop, response_format]
        )

    def perform_action(self, connection: str, action: str, **kwargs) -> None:
        return self.connection_manager.perform_action(connection, action, **kwargs)

    def loop(self):
        """Main agent loop for autonomous behavior"""
        if not self.is_llm_set:
            self._setup_llm_provider()

        system_prompt = self._construct_system_prompt()
        system_prompt = system_prompt.format(
            tool=self.tasks
        )

        logger.info("\n🚀 Starting agent loop...")
        logger.info("Press Ctrl+C at any time to stop the loop.")
        print_h_bar()

        # logger.info(f"System prompt: {system_prompt}")

        time.sleep(2)
        logger.info("Starting loop in 5 seconds...")
        for i in range(5, 0, -1):
            logger.info(f"{i}...")
            time.sleep(1)
        try:
            while True:
                success = False
                if self.name == "DeployTokenAgent":
                    execute_action(self, "deploy-token")
                    success = True
                else:
                    try:
                        n_calls, n_badcalls = 0, 0
                        self.steps = 0
                        self.answer = None
                        prompt = ""
                        for i in range(1, 5):
                            n_calls += 1
                            thought_action = self.prompt_llm(prompt=prompt + f"Thought {i}:",
                                                            system_prompt=system_prompt,
                                                            stop=[f"Observation {i}:"])
                            logger.info(f"thought_action {thought_action}...")
                            try:
                                thought, action_name = thought_action.strip().split(
                                    f"Action {i}:")
                                action_name = action_name.strip()
                            except:
                                logger.info(f'ohh... {thought_action}')
                                n_badcalls += 1
                                n_calls += 1
                                thought = thought_action.strip().split('\n')[0]
                                action_name = self.prompt_llm(prompt=prompt + f"Thought {i}: {thought}\nAction {i}:",
                                                            system_prompt=system_prompt,
                                                            stop=[f"\n"]).strip()
                            logger.info(
                                f"action_name {action_name[0], action_name[0].lower(), action_name[1:]}...")
                            obs, r, done, info = self.env(
                                action_name[0].lower() + action_name[1:])
                            logger.info(f"return env {obs, r, done, info}...")
                            step_str = f"Thought {i}: {thought}\nAction {i}: {action_name}\nObservation {i}: {obs}\n"
                            prompt += step_str
                            logger.info(f"{prompt}...")
                            if done:
                                break
                        if not done:
                            obs, r, done, info = self.env("finish[]")
                        task_exists = any(action['name'] == 'post-tweet' for action in self.tasks)
                        if task_exists:
                            logger.info(f"post-tweet started ...")
                            execute_action(self, "post-tweet")
                        logger.info(
                            f"\n⏳ Waiting {self.loop_delay} seconds before next loop...")
                        print_h_bar()
                        time.sleep(self.loop_delay if success else 60)
    
                    except Exception as e:
                        logger.error(f"\n❌ Error in agent loop iteration: {e}")
                        logger.info(
                            f"⏳ Waiting {self.loop_delay} seconds before retrying...")
                        time.sleep(self.loop_delay)
        except KeyboardInterrupt:
            logger.info("\n🛑 Agent loop stopped by user.")
            return

    def prompt_agent(self, prompt: str):
        if not self.is_llm_set:
            self._setup_llm_provider()

        system_prompt = self._construct_system_prompt()
        system_prompt = system_prompt.format(
            tool=self.tasks
        )
        logger.info(f"system prompt: {system_prompt}")
        logger.info("\n🚀 Starting prompt agent")

        try:
            # CHOOSE AN ACTION
            # TODO: Add agentic action selection
            n_calls, n_badcalls = 0, 0
            self.steps = 0
            self.answer = None
            for i in range(1, 5):
                n_calls += 1
                thought_action = self.prompt_llm(prompt=prompt + f"Thought {i}:",
                                                 system_prompt=system_prompt,
                                                 stop=[f"Observation {i}:"])
                logger.info(f"thought_action {thought_action}...")
                try:
                    thought, action_name = thought_action.strip().split(
                        f"Action {i}:")
                    action_name = action_name.strip()
                except:
                    logger.info(f'ohh... {thought_action}')
                    n_badcalls += 1
                    n_calls += 1
                    thought = thought_action.strip().split('\n')[0]
                    action_name = self.prompt_llm(prompt=prompt + f"Thought {i}: {thought}\nAction {i}:",
                                                  system_prompt=system_prompt,
                                                  stop=[f"\n"]).strip()
                logger.info(
                    f"action_name {action_name[0], action_name[0].lower(), action_name[1:]}...")
                obs, r, done, info = self.env(
                    action_name[0].lower() + action_name[1:])
                logger.info(f"return env {obs, r, done, info}...")
                step_str = f"Thought {i}: {thought}\nAction {i}: {action_name}\nObservation {i}: {obs}\n"
                prompt += step_str
                logger.info(f"{prompt}...")
                if done:
                    break
            if not done:
                obs, r, done, info = self.env("finish[]")
            return self.answer
        except KeyboardInterrupt:
            logger.info("\n🛑 Agent loop stopped by user.")
            return

    def env(self, action):
        attempts = 0
        while attempts < 10:
            try:
                return self.step(action)
            except:
                attempts += 1

    def _get_info_env(self):
        return {
            "steps": self.steps,
            "answer": self.answer,
        }

    def step(self, action):
        reward = 0
        done = False
        action = action.strip()
        if self.answer is not None:  # already finished
            done = True
            return self.obs, reward, done, self._get_info_env()

        if action.startswith("call[") and action.endswith("]"):
            entity = action[len("call["):-1]
            logger.info(f"action to be invoked: {entity}")
            self.obs = execute_action(self, entity)
        elif action.startswith("finish[") and action.endswith("]"):
            answer = action[len("finish["):-1]
            self.answer = answer
            done = True
            self.obs = f"Episode finished, reward = {reward}\n"
        elif action.startswith("think[") and action.endswith("]"):
            self.obs = "Nice thought."
        else:
            self.obs = "Invalid action: {}".format(action)

        self.steps += 1

        return self.obs, reward, done, self._get_info_env()
