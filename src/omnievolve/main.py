"""OmniEvolve entry point."""

from __future__ import annotations


def main() -> None:
    """Launch the OmniEvolve CLI."""
    from omnievolve.cli import app

    app()


if __name__ == "__main__":
    main()
