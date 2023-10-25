import numpy as np
from pedsim_waypoint_plugin.pedsim_waypoint_generator import PedsimWaypointGenerator, AgentStates, WaypointPluginName, WaypointPlugin


@PedsimWaypointGenerator.register(WaypointPluginName.SPINNY)
class Plugin_Backwards(WaypointPlugin):

    angle: float

    def __init__(self):
        self.angle = 0

    def callback(self, agent_states: AgentStates) -> AgentStates:
        
        self.angle += 5
        if self.angle > 360:
            self.angle = 0

        for agent in agent_states:
            agent.pose.orientation.x = 0
            agent.pose.orientation.y = 0
            agent.pose.orientation.z = self.angle * np.pi/180
            agent.pose.orientation.w = 1 - np.sqrt(agent.pose.orientation.z)

        print(self.angle)

        return agent_states