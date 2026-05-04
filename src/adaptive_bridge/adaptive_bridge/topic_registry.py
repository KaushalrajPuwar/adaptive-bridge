"""
Deterministic topic-route builder and registry.

The :class:`TopicRegistry` consumes a list of ``TopicConfig`` objects and
builds a dict of ``TopicRoute`` instances.  It enforces uniqueness of
route IDs and topic names, provides deterministic name-sanitisation, and
exposes registry-level queries (``list_routes()``, ``get_route()``) for
the proxy and diagnostics subsystems.
"""
from __future__ import annotations

from collections import OrderedDict

from .config_types import TopicConfig
from .models import TopicRoute


def sanitize_topic_name(topic: str) -> str:
    base = (topic or "").strip().strip("/")
    if not base:
        return "topic"
    sanitized = base.replace("/", "_")
    ascii_only = "".join(ch for ch in sanitized if ord(ch) < 128)
    return ascii_only or "topic"


class TopicRegistry:
    """Registry for deterministic route construction and uniqueness guarantees."""

    def __init__(self) -> None:
        self._routes: "OrderedDict[str, TopicRoute]" = OrderedDict()

    def build_routes(self, topics_cfg: list[TopicConfig]) -> dict[str, TopicRoute]:
        routes: "OrderedDict[str, TopicRoute]" = OrderedDict()
        seen_inputs: set[str] = set()
        seen_outputs: set[str] = set()

        for topic in topics_cfg:
            if topic.id in routes:
                raise ValueError(f"duplicate topic_id: {topic.id}")
            if topic.input_topic in seen_inputs:
                raise ValueError(f"duplicate input_topic: {topic.input_topic}")

            critical_output = topic.critical_output or f"/adaptive_bridge/critical/{sanitize_topic_name(topic.input_topic)}"
            noncritical_output = topic.noncritical_output or f"/adaptive_bridge/noncritical/{sanitize_topic_name(topic.input_topic)}"

            if critical_output == noncritical_output:
                raise ValueError(f"critical/noncritical outputs collide for topic_id={topic.id}")
            if critical_output in seen_outputs:
                raise ValueError(f"duplicate critical_output: {critical_output}")
            if noncritical_output in seen_outputs:
                raise ValueError(f"duplicate noncritical_output: {noncritical_output}")

            seen_inputs.add(topic.input_topic)
            seen_outputs.add(critical_output)
            seen_outputs.add(noncritical_output)

            routes[topic.id] = TopicRoute(
                topic_id=topic.id,
                input_topic=topic.input_topic,
                critical_output=critical_output,
                noncritical_output=noncritical_output,
                message_type=topic.message_type,
            )

        self._routes = routes
        return dict(self._routes)

    def get_route(self, topic_id: str) -> TopicRoute:
        if topic_id not in self._routes:
            raise ValueError(f"unknown topic_id: {topic_id}")
        return self._routes[topic_id]

    def list_routes(self) -> list[TopicRoute]:
        return list(self._routes.values())

    def export_routes(self) -> list[dict[str, str]]:
        return [r.to_dict() for r in self._routes.values()]
