from dataclasses import dataclass
from typing import Any, Callable


ToolHandler = Callable[
    [str, dict[str, Any]],
    dict[str, Any],
]


@dataclass(frozen=True)
class ToolDefinition:
    """
    Metadata and executable handler for one NOVA tool.
    """

    name: str
    description: str
    actions: tuple[str, ...]
    handler: ToolHandler


class ToolRegistry:
    """
    Generic registry for NOVA's executable tools.

    The registry keeps tool registration, discovery,
    metadata, and execution separate from the router.

    Future tools such as:
    - calendar
    - email
    - messaging
    - web
    - documents
    - system APIs

    can be registered without changing the registry itself.
    """

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        actions: list[str] | tuple[str, ...],
        handler: ToolHandler,
    ) -> None:
        """
        Register a new tool.

        Raises:
            ValueError: if the name is empty or already registered.
        """

        tool_name = str(name).strip()

        if not tool_name:
            raise ValueError("Tool name cannot be empty.")

        if tool_name in self._tools:
            raise ValueError(
                f"Tool '{tool_name}' is already registered."
            )

        normalized_actions = tuple(
            str(action).strip()
            for action in actions
            if str(action).strip()
        )

        self._tools[tool_name] = ToolDefinition(
            name=tool_name,
            description=str(description).strip(),
            actions=normalized_actions,
            handler=handler,
        )

    def unregister(self, name: str) -> bool:
        """
        Remove a registered tool.

        Returns:
            True if the tool existed and was removed.
            False otherwise.
        """

        return self._tools.pop(
            str(name).strip(),
            None,
        ) is not None

    def get(self, name: str) -> ToolDefinition | None:
        """
        Return a registered tool definition.
        """

        return self._tools.get(
            str(name).strip()
        )

    def has(self, name: str) -> bool:
        """
        Check whether a tool is registered.
        """

        return str(name).strip() in self._tools

    def list_tools(self) -> list[dict[str, Any]]:
        """
        Return metadata for all registered tools.

        Handlers themselves are intentionally not exposed.
        """

        return [
            {
                "name": tool.name,
                "description": tool.description,
                "actions": list(tool.actions),
            }
            for tool in self._tools.values()
        ]

    def get_available_tools(self) -> list[dict[str, Any]]:
        """
        Return the tools currently available to NOVA's
        decision-making layer.

        This is intentionally metadata-only so the planner
        can inspect capabilities without direct access to
        executable handlers.
        """

        return self.list_tools()

    def execute(
        self,
        name: str,
        user_id: str,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute a registered tool.
        """

        tool_name = str(name).strip()
        payload = data or {}

        tool = self.get(tool_name)

        if tool is None:
            return {
                "success": False,
                "tool": None,
                "action": None,
                "result": None,
                "error": (
                    f"No tool is registered for "
                    f"name '{tool_name}'."
                ),
            }

        try:
            return tool.handler(
                user_id,
                payload,
            )

        except Exception as exc:
            return {
                "success": False,
                "tool": tool_name,
                "action": None,
                "result": None,
                "error": (
                    f"Tool '{tool_name}' failed: "
                    f"{str(exc)}"
                ),
            }