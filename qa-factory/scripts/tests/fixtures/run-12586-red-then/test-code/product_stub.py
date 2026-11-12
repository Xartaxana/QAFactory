# Stand-in for everything the verbatim test function of TC-003 (put_project_change_into_occupied_project.py) takes from the
# harness and the product (t-1561, key K-R4-S of spec t-1508 5.4). A test composes ONE module: this prelude, then the verbatim
# function below it, so the function's own lines are untouched. The product's answer is canned: a PUT that moves an MS Teams
# integration answers `400 Project mismatch` (the live shape: the move is refused, but with the WRONG reason), and nothing changes.
# Then 1 holds (4xx), Then 2 FAILS ("Project mismatch" is in the body), Then 3 and 4 hold: the red test the diagnostic run is for.
import functools
import inspect
from types import SimpleNamespace


class Pytest:
    """`pytest.mark.<anything>(...)` is a no-op decorator, except `api`: the innermost mark of the function hands it the stub fixtures."""

    class Mark:
        def __getattr__(self, name):
            if name == "api":
                return self.inject
            return self.plain

        @staticmethod
        def plain(*args, **kwargs):          # `@pytest.mark.x` bare, or `@pytest.mark.x(...)`: the function stays as it is
            return args[0] if len(args) == 1 and not kwargs and callable(args[0]) else (lambda function: function)

        @staticmethod
        def inject(function):
            @functools.wraps(function)
            def run():
                return function(**{name: FIXTURES[name]() for name in inspect.signature(function).parameters})
            return run

    mark = Mark()


pytest = Pytest()


class Row(SimpleNamespace):
    def model_dump(self):
        return dict(vars(self))


class Product:
    """Two projects, each with the MS Teams integrations the test created; a move is always refused with `400 Project mismatch`."""

    def __init__(self):
        self.rows = {"source": [], "target": []}
        self.count = 0

    def make(self, project):
        self.count += 1
        row = Row(id=f"integration-{self.count}", project=project, alias="ms-teams")
        self.rows[project].append(row)
        return row, None


PRODUCT = Product()
CredentialTypes = SimpleNamespace(MS_TEAMS="MS_TEAMS")


def ms_teams_credentials(assistant_id):
    return {"assistant": assistant_id}


class IntegrationUtils:
    def find_project_integration(self, project, integration_id):
        return next(row for row in PRODUCT.rows[project] if row.id == integration_id)

    def change_project_status(self, moving, project, credential_values=None):
        return 400, "Project mismatch: the integration does not belong to the target project"

    def list_project_integrations(self, project, credential_type):
        return list(PRODUCT.rows[project])


FIXTURES = {
    "project_pair": lambda: SimpleNamespace(source="source", target="target"),
    "ms_teams_integration_factory": lambda: PRODUCT.make,
    "project_assistant_factory": lambda: (lambda project: SimpleNamespace(id=f"assistant-of-{project}")),
    "integration_utils": lambda: IntegrationUtils(),
}


class Failed(AssertionError):
    pass


def assert_that(actual, matcher, reason=""):
    if not matcher(actual):
        raise Failed(reason)


def all_of(*matchers):
    return lambda value: all(m(value) for m in matchers)


def greater_than_or_equal_to(limit):
    return lambda value: value >= limit


def less_than(limit):
    return lambda value: value < limit


def is_not(matcher):
    return lambda value: not matcher(value)


def contains_string(text):
    return lambda value: text in value


def contains_exactly(*items):
    return lambda value: list(value) == list(items)


