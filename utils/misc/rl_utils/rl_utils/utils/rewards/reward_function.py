from typing import Any, Callable, Dict, List, Tuple

import numpy as np
import rospy

from .constants import REWARD_CONSTANTS
from .utils import load_rew_fnc


class RewardFunction:
    _rew_func_name: str
    _robot_radius: float
    _safe_dist: float
    _goal_radius: float

    _curr_dist_to_path: float
    _safe_dist_breached: bool

    _curr_reward: float
    _info: Dict[str, Any]

    _rew_fnc_dict: Dict[str, Dict[str, Any]]
    _reward_units: List["RewardUnit"]

    def __init__(
        self,
        rew_func_name: str,
        robot_radius: float,
        goal_radius: float,
        safe_dist: float,
        *args,
        **kwargs,
    ):
        """This class represents a reward function for a reinforcement learning environment.

        Args:
            rew_func_name (str): Name of the yaml file that contains the reward function specifications.
            robot_radius (float): Radius of the robot.
            goal_radius (float): Radius of the goal.
            safe_dist (float): Safe distance of the agent.
        """
        self._rew_func_name = rew_func_name
        self._robot_radius = robot_radius
        self._safe_dist = safe_dist
        self._goal_radius = goal_radius

        # globally accessible and required information for RewardUnits
        self._curr_dist_to_path: float = None
        self._safe_dist_breached: bool = None

        self._curr_reward = 0
        self._info = {}

        self._rew_fnc_dict = load_rew_fnc(self._rew_func_name)
        self._reward_units: List["RewardUnit"] = self._setup_reward_function()

    def _setup_reward_function(self) -> List["RewardUnit"]:
        """Sets up the reward function.

        Returns:
            List[RewardUnit]: List of reward units for calculating the reward.
        """
        import rl_utils.utils.rewards as rew_pkg

        return [
            rew_pkg.RewardUnitFactory.instantiate(unit_name)(
                reward_function=self, **kwargs
            )
            for unit_name, kwargs in self._rew_fnc_dict.items()
        ]

    def add_reward(self, value: float):
        """Adds the specified value to the current reward.

        Args:
            value (float): Reward to be added. Typically called by the RewardUnit.
        """
        self._curr_reward += value

    def add_info(self, info: Dict[str, Any]):
        """Adds the specified information to the reward function's info dictionary.

        Args:
            info (Dict[str, Any]): RewardUnits information to be added.
        """
        self._info.update(info)

    def _reset(self):
        """Reset on every environment step."""
        self._curr_reward = 0
        self._info = {}

    def reset(self):
        """Reset before each episode."""
        self.goal_radius = rospy.get_param("/goal_radius", 0.3)
        self._curr_dist_to_path = None

        for reward_unit in self._reward_units:
            reward_unit.reset()

    def calculate_reward(self, laser_scan: np.ndarray, *args, **kwargs) -> None:
        """Calculates the reward based on several observations.

        Args:
            laser_scan (np.ndarray): Array containing the laser data.
        """
        self._reset()
        self.set_safe_dist_breached(laser_scan)

        for reward_unit in self._reward_units:
            if self.safe_dist_breached and not reward_unit.on_safe_dist_violation:
                continue
            reward_unit(laser_scan=laser_scan, **kwargs)

    def get_reward(self, *args, **kwargs) -> Tuple[float, Dict[str, Any]]:
        """Retrieves the current reward and info dictionary.

        Returns:
            Tuple[float, Dict[str, Any]]: Tuple of the current timesteps reward and info.
        """
        self.calculate_reward(**kwargs)
        return self._curr_reward, self._info

    @property
    def robot_radius(self) -> float:
        return self._robot_radius

    @property
    def goal_radius(self) -> float:
        return self._goal_radius

    @goal_radius.setter
    def goal_radius(self, value) -> None:
        if value < REWARD_CONSTANTS.MIN_GOAL_RADIUS:
            raise ValueError(
                f"Goal radius smaller than {REWARD_CONSTANTS.MIN_GOAL_RADIUS}"
            )
        self._goal_radius = value

    @property
    def curr_dist_to_path(self) -> float:
        return self._curr_dist_to_path

    @curr_dist_to_path.setter
    def curr_dist_to_path(self, value: float) -> None:
        self._curr_dist_to_path = value

    @property
    def safe_dist_breached(self) -> bool:
        return self._safe_dist_breached

    def set_safe_dist_breached(self, laser_scan: np.ndarray) -> None:
        self._safe_dist_breached = laser_scan.min() <= self._safe_dist

    def __repr__(self) -> str:
        format_string = self.__class__.__name__ + "("
        for name, params in self._rew_fnc_dict.items():
            format_string += "\n"
            format_string += f"{name}: {params}"
        format_string += "\n)"
        return format_string
