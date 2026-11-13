"""The release controller: every phase, assembled from its operation layers."""

from .operations import ReportingOperations


class Controller(ReportingOperations):
    """Runs the deployment phases on a Catalog host; one instance per invocation."""
