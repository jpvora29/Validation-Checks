# CLAUDE.md: Python Design & Typing Standards

These rules apply to all Python code you write or modify in this repo. They follow the design philosophy popularised by ArjanCodes: simple, composable, loosely coupled code with strict static types. When a rule conflicts with the existing code style in a file, follow the rule for new code and flag the inconsistency instead of rewriting unrelated code.

## 0. Guiding Principles

1. **Simplicity first.** Use the simplest construct that works: function > dataclass > class with behaviour > class hierarchy. Do not introduce a pattern unless it removes a real, present problem (duplication, tight coupling, untestable code, a growing if/elif chain).
2. **Composition over inheritance.** Inheritance is the last resort, never the default for code reuse.
3. **Depend on abstractions, inject concrete things.** High-level logic must not construct its own collaborators (DB, LLM client, HTTP, file system, clock). Pass them in.
4. **Separate concerns.** Keep I/O, business logic, and presentation in different modules. Business logic should be pure and testable without mocks where possible.
5. **Make illegal states unrepresentable.** Use types (enums, Literals, frozen dataclasses, NewType) so invalid data cannot be built.
6. **Explicit over implicit.** No hidden globals, no magic, no mutable module-level state.

## 1. Strict Typing (non-negotiable)

- Every function, method, and attribute has full type annotations, including return types (`-> None` too).
- Code must pass `mypy --strict` (or `pyright` strict) with zero errors. Do not silence errors with a blanket `# type: ignore`. If unavoidable, use a narrow `# type: ignore[error-code]` with a one-line reason.
- **Never use `Any`** unless interfacing with an untyped third-party library, and then isolate it at the boundary and convert to typed values immediately.
- Use modern syntax (Python 3.11+): `list[int]`, `dict[str, int]`, `X | None`, `typing.Self`, `typing.override`, PEP 695 generics (`def f[T](x: T) -> T`) where the project's Python version allows. Add `from __future__ import annotations` only if targeting older versions.
- Prefer abstract collection types in parameters (`Sequence`, `Mapping`, `Iterable`) and concrete types in return values.
- Use `Protocol` for structural interfaces, `Callable[[...], ...]` for single-method behaviours, `TypeVar`/generics for reusable containers, `Literal` and `Enum`/`StrEnum` for closed sets of values, `TypedDict` only for external dict-shaped data, `NewType` for domain primitives (`UserId`, `Currency`), `Final` for constants, `@overload` when return type depends on arguments.
- Use `@typing.override` on every overriding method.
- Parse, don't validate: convert untrusted input (JSON, API responses, LLM output, SQL rows, env vars) into typed models at the boundary (Pydantic `BaseModel` or validated dataclasses). Core logic only handles validated types.
- No bare `dict` or `tuple` as ad-hoc data structures passed between functions. Create a dataclass or model.

## 2. Data Modelling

- Use `@dataclass(frozen=True, slots=True, kw_only=True)` by default for value objects. Mutable dataclasses only when mutation is required and justified.
- Use Pydantic models for I/O boundaries (config, API payloads, LLM structured output). Use plain dataclasses for internal domain objects.
- Use `field(default_factory=...)` for mutable defaults. Never use mutable default arguments.
- Use `enum.Enum`/`StrEnum` instead of magic strings and ints.
- Keep models free of I/O and heavy logic. Behaviour that belongs to the data (validation, derived values) goes in methods or `@property`; orchestration does not.

## 3. Functions vs Classes

- **Default to functions.** Pure functions with explicit inputs and outputs are the easiest to test and compose.
- Do not create a class that only has `__init__` plus one method. Use a function (or `functools.partial` to bind config).
- Do not use classes as namespaces for static methods. Use a module.
- Use a class when you need to hold state with behaviour, enforce invariants, or implement a Protocol that needs several methods.
- Keep functions small and single-purpose. Aim for one level of abstraction per function and 3 or fewer positional parameters; beyond that use keyword-only arguments or a parameter dataclass.

## 4. SOLID, Applied Pragmatically

- **S**: One reason to change per module or class. Split "fetch + transform + render + save" into separate units.
- **O**: Extend behaviour by adding a new strategy/handler/plugin, not by editing an if/elif chain.
- **L**: Subtypes must honour the base contract. Don't narrow parameter types or raise new exceptions in overrides.
- **I**: Small, focused Protocols (one to three methods). Callers should depend only on what they use.
- **D**: Depend on Protocols/Callables, not concrete classes. Wire concrete implementations at the composition root.

## 5. Design Patterns: How to Implement Them in Python

Use the Pythonic form of each pattern. Do not port Java-style class hierarchies.

### 5.1 Strategy (replace if/elif on type or mode)
- Prefer a `Callable` type alias or a `Protocol` with one method. Pass the strategy in as an argument.
- For stateless strategies use plain functions. For configurable ones use `functools.partial` or a small frozen dataclass implementing the Protocol.

```python
from collections.abc import Callable

type PricingStrategy = Callable[[float], float]

def no_discount(price: float) -> float: return price
def percentage_discount(pct: float) -> PricingStrategy:
    return lambda price: price * (1 - pct)

def checkout(price: float, strategy: PricingStrategy) -> float:
    return strategy(price)
```

### 5.2 Factory / Registry (create objects from a string or enum key)
- Use a typed dict registry mapping a key to a constructor or callable, with a `register` decorator when plugins are needed. Avoid giant if/elif factories.
- Return a `Protocol` type, not a concrete class.

### 5.3 Dependency Injection
- Constructor injection for classes, parameter injection for functions. No service locators, no hidden singletons.
- Build the object graph in one place (`main()` or a `composition_root.py`). Business modules never import concrete infrastructure.
- Prefer passing `Protocol`-typed collaborators so tests can pass simple fakes without `mock.patch`.

### 5.4 Observer / Pub-Sub / Event Bus
- Use a small typed event bus: `subscribe(event_type, handler)` and `post(event)`, where handlers are `Callable[[E], None]`.
- Events are frozen dataclasses. Decouple producers from consumers (logging, notifications, metrics) with events instead of direct calls.

### 5.5 Command
- Represent an action as a callable or a frozen dataclass with `execute()` (and `undo()` if needed). Use for task queues, undo/redo, scheduling, and agent tool calls.

### 5.6 Decorator (functional wrappers)
- Use for cross-cutting concerns (retry, timing, caching, logging, auth). Type decorators with `ParamSpec` and `TypeVar` so signatures are preserved, and use `functools.wraps`.
- Use the GoF object-wrapping Decorator (same Protocol, wraps an inner instance) when behaviour must be layered on an object, e.g. `CachedRepository(inner=SqlRepository(...))`.

### 5.7 Adapter / Facade
- Wrap third-party SDKs (Azure OpenAI, ChromaDB, win32com, etc.) behind your own small Protocol so the rest of the code never imports the SDK directly and the vendor can be swapped or faked.
- Use a Facade to expose one simple function or class over a messy subsystem.

### 5.8 Repository / Unit of Work (data access)
- Define a `Protocol` per aggregate (`get`, `add`, `list`). Keep SQL and ORM details inside the implementation. Business logic receives the repository, not a connection.

### 5.9 Builder
- Prefer keyword-only arguments plus dataclass defaults. Use a Builder only when construction is multi-step with ordering rules, and make it return a new immutable object from `build()`.

### 5.10 Template Method / Pipeline
- Prefer a pipeline of functions (`list[Callable[[T], T]]` reduced in order) over an abstract base class with hooks. Use `functools.reduce` or a small `Pipeline` class generic over `T`.
- Use ABC template method only when the algorithm skeleton truly must be fixed and shared.

### 5.11 State
- Model finite states with `Enum` plus a transition table (`dict[tuple[State, Event], State]`) or one class per state implementing a Protocol. Use `match` for exhaustive handling, and `assert_never` in the default branch.

### 5.12 Singleton: avoid
- Do not use the Singleton pattern. Use a single instance created in the composition root and injected. A module-level constant is acceptable only for immutable values.

### 5.13 Result / Error Handling
- Use specific, custom exception types derived from a single project base exception. Never `except Exception: pass`.
- For expected failures in a pipeline, consider a typed `Result[T, E]` (`Ok`/`Err` frozen dataclasses). Use exceptions for truly exceptional cases. Be consistent within a module.
- Catch narrowly, at the layer that can act on the error. Preserve causes with `raise ... from e`.

## 6. Protocol vs ABC

- Default to `typing.Protocol` for interfaces (structural typing; no inheritance coupling). Mark `@runtime_checkable` only if `isinstance` checks are genuinely needed.
- Use `abc.ABC` only when you need shared implementation in the base class or to enforce explicit subclassing.
- Keep Protocols next to the code that **uses** them (consumer-owned interfaces), not next to implementations.

## 7. Project Structure

```
project/
├── pyproject.toml
├── CLAUDE.md
├── src/<package>/
│   ├── domain/          # pure models + business rules, no I/O
│   ├── services/        # use cases / orchestration, depend on Protocols
│   ├── adapters/        # DB, LLM, HTTP, file, COM implementations
│   ├── interfaces.py    # shared Protocols (or per-module)
│   ├── config.py        # typed settings (Pydantic Settings)
│   └── main.py          # composition root: wires everything
└── tests/               # mirrors src/ layout
```

- Dependency direction: `main` → `services` → `domain`; `adapters` implement Protocols used by `services`. `domain` imports nothing from `adapters` or `services`.
- No circular imports. If two modules need each other, extract the shared abstraction.
- Keep modules cohesive and under roughly 300 lines. Split by responsibility, not by type (avoid a dumping-ground `utils.py`).

## 8. Code Style & Quality

- Format and lint with **ruff** (`ruff format`, `ruff check`) and type-check with **mypy --strict**. Code must pass all three before you consider the task done.
- Names: descriptive, intention-revealing; `snake_case` functions and variables, `PascalCase` classes, `UPPER_CASE` constants. No single-letter names except short loop indices or type variables.
- Use `pathlib.Path`, f-strings, context managers, `enumerate`/`zip`, comprehensions (but not nested beyond readability), and `match` for structural branching.
- Use `logging` (module-level `logger = logging.getLogger(__name__)`), never `print`, outside CLI output.
- Docstrings: concise, on public modules, classes, and functions, explaining *why* and the contract (not restating the signature). Comments explain non-obvious decisions only.
- No dead code, no commented-out code, no TODOs without context.
- Avoid premature optimisation, but never use mutable global state or hidden side effects at import time.

## 9. Testing

- Use **pytest**. Test behaviour through public interfaces. Arrange-Act-Assert structure, one logical assertion focus per test.
- Because collaborators are injected, test with small hand-written fakes that satisfy the Protocol rather than heavy `mock.patch` usage. Use `monkeypatch` or fixtures for the rest.
- Use `pytest.mark.parametrize` for table-driven cases. Use fixtures for shared setup.
- Pure domain logic gets unit tests. Adapters get a small number of integration tests. Keep tests typed too.
- Every bug fix gets a regression test.

## 10. Workflow When Generating or Refactoring Code

1. Briefly state the design you intend (which pattern(s), and why) before writing large changes. If no pattern is warranted, say so and keep it simple.
2. Identify the seams: what should be an injected Protocol or Callable, and what stays a plain function.
3. Write the types first (models, Protocols), then the logic, then the wiring in the composition root.
4. Keep changes minimal and focused. Do not refactor unrelated code. Mention opportunities instead.
5. Run `ruff format`, `ruff check`, `mypy --strict`, and `pytest`. Fix everything before reporting done.
6. In the final summary, list the patterns applied, new Protocols or interfaces introduced, and any deliberate trade-offs or `type: ignore` usages.

## 11. Anti-Patterns to Reject

- God classes or functions doing fetch, transform, and save together.
- Inheritance hierarchies used purely for code reuse; deep inheritance (more than two levels).
- if/elif or `match` chains on type/mode that keep growing (use Strategy or a registry).
- Constructing dependencies inside business logic (`self.client = OpenAI()` inside a service).
- Singletons, module-level mutable state, and global config reads scattered through the code.
- Stringly-typed code (magic strings/ints) and untyped dicts as data models.
- Catch-all exception handlers and swallowed errors.
- `Any`, missing annotations, blanket `type: ignore`.
- Over-engineering: abstract factories, builders, or layers added "just in case".