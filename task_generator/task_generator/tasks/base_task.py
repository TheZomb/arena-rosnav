import os
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from rospkg import RosPack
import rospy

from rosgraph_msgs.msg import Clock
from task_generator.constants import Constants
from task_generator.manager.map_manager import MapManager
from task_generator.manager.robot_manager import RobotManager
from task_generator.manager.obstacle_manager import ObstacleManager
from task_generator.utils import ModelLoader


class Props_Manager:
    obstacle_manager: ObstacleManager
    robot_managers: List[RobotManager]
    map_manager: MapManager


class Props_Modelloader:
    model_loader: ModelLoader
    dynamic_model_loader: ModelLoader


class Props_Namespace:
    namespace: str
    namespace_prefix: str


class Props_(Props_Manager, Props_Modelloader, Props_Namespace):
    ...


class BaseTask(Props_):
    """
    Base Task as parent class for all other tasks.
    """

    clock: Clock
    last_reset_time: int

    def __init__(
        self,
        obstacle_manager: ObstacleManager,
        robot_managers: List[RobotManager],
        map_manager: MapManager,
        namespace: str = "",
        *args, **kwargs
    ):
        self.namespace = namespace
        self.namespace_prefix = f"/{namespace}/" if os.path.basename(
            namespace) else ""

        self.obstacle_manager = obstacle_manager
        self.robot_managers = robot_managers
        self.map_manager = map_manager

        rospy.Subscriber("/clock", Clock, self._clock_callback)
        self.last_reset_time = 0
        self.clock = Clock()

        self.set_up_robot_managers()

        self.model_loader = ModelLoader(os.path.join(
            RosPack().get_path("arena-simulation-setup"), "obstacles", "static_obstacles"))
        self.dynamic_model_loader = ModelLoader(os.path.join(
            RosPack().get_path("arena-simulation-setup"), "obstacles", "dynamic_obstacles"))

    @staticmethod
    def reset_helper(parent: Type["BaseTask"]) -> Callable[..., Callable[..., bool]]:
        """
        Decorate reset(self, ...)->Callable[..., bool] in any BaseTask subclass with @BaseTask.reset_helper(parent=parent_class) to bind into the reset chain.
        First the reset body is called, then the chain is traversed up to BaseTask and then back down to the callback returned by reset. Return True from this callback to indicate all tasks are completed and the simulation can be shut down.
        @parent: direct parent class
        """
        def outer(fn: Callable[..., Tuple[Dict[str, Any], Optional[Callable[[], bool]]]]) -> Callable[..., bool]:
            def _reset(self, callback: Callable[[], bool], **kwargs) -> bool:
                overrides, fn_callback = fn(self, **kwargs)
                if fn_callback is None:
                    return False
                return parent.reset(self, callback=callback, **{**overrides, **kwargs}) or fn_callback()
            return _reset
        return outer

    def reset(self, callback: Callable[[], bool], **kwargs) -> bool:
        """
        Calls a passed reset function (usually the tasks own reset)
        inside a loop so when the callback fails once it is tried
        again. After MAX_RESET_FAIL_TIMES the reset is considered
        as fail and the simulation is shut down.
        """
        fails = 0
        return_val = False

        self.last_reset_time = self.clock.clock.secs

        # TODO wait for previous reset to be done

        while fails < Constants.MAX_RESET_FAIL_TIMES:
            try:
                return_val = callback()
                break

            except rospy.ServiceException as e:
                rospy.logwarn(repr(e))
                fails += 1

        else:
            rospy.signal_shutdown("Reset error!")
            raise Exception("reset error!")

        return return_val

    @property
    def is_done(self) -> bool:
        if self.clock.clock.secs - self.last_reset_time > Constants.TIMEOUT:
            return True

        for manager in self.robot_managers:
            if not manager.is_done:
                return False

        return True

    @property
    def robot_names(self) -> List[str]:
        return [manager.name for manager in self.robot_managers]

    def set_up_robot_managers(self):
        for manager in self.robot_managers:
            manager.set_up_robot()

    def _clock_callback(self, clock: Clock):
        self.clock = clock
