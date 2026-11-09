"""Dependency-aware invalidation for corrected claims and upstream artifacts."""
from collections import defaultdict, deque


def descendants(root_ids: set[str], edges: list[tuple[str, str]]) -> set[str]:
    """Return transitive dependents. Edge order is (parent_artifact, dependent_artifact)."""
    graph: dict[str, set[str]] = defaultdict(set)
    for parent, child in edges:
        graph[parent].add(child)
    found: set[str] = set()
    queue = deque(root_ids)
    while queue:
        node = queue.popleft()
        for child in graph[node]:
            if child not in found and child not in root_ids:
                found.add(child)
                queue.append(child)
    return found


def invalidation_plan(changed_artifact_ids: set[str], edges: list[tuple[str, str]]) -> dict[str, list[str]]:
    """Plan only; caller creates superseded/new versions, never deletes artifacts."""
    return {"roots": sorted(changed_artifact_ids), "dependent_artifacts_to_supersede": sorted(descendants(changed_artifact_ids, edges))}
