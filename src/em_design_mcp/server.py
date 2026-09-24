from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .registries.model_profile_registry import ModelProfileRegistry
from .registries.package_registry import PackageRegistry
from .registries.problem_spec_registry import ProblemSpecRegistry
from .registries.verifier_registry import VerifierRegistry
from .tools.agent_tools import register_agent_tools
from .utils.dotenv import load_project_dotenv


def create_server() -> FastMCP:
    load_project_dotenv()
    server = FastMCP(
        "em-design-mcp",
        instructions=(
            "Agent-first COMSOL execution service. Discover once, inspect one contract, "
            "then start a persistent run. Prefer server-side waits and compact results; "
            "do not poll more frequently than the returned revision changes."
        ),
    )
    packages = PackageRegistry()
    model_profiles = ModelProfileRegistry(packages=packages)
    problem_specs = ProblemSpecRegistry(packages=packages)
    verifiers = VerifierRegistry(packages)

    register_agent_tools(server, packages, model_profiles, problem_specs, verifiers)
    return server


def main() -> None:
    server = create_server()
    server.run()


if __name__ == "__main__":
    main()
