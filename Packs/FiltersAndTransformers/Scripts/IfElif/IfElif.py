import demistomock as demisto
from CommonServerPython import *
from collections.abc import Callable
from functools import reduce, partial
import ast
import re

ARGS = demisto.args()
FLAGS = argToList(ARGS.get('flags'))


def load_variables():
    variables = {}
    assignments = ARGS.get('variables', '').splitlines()
    for assign in assignments:
        left, right = assign.strip().split('=', 1)
        try:
            right = ast.literal_eval(right)
        except Exception:  # is a string
            right = right.strip()
        variables[left.strip()] = right
    variables |= {
        'true': True,
        'false': False,
        'null': None,
        'VALUE': ARGS['value'],
    }
    return variables


VARIABLES = load_variables()

REGEX_FLAGS = (
    re.DOTALL * ('regex_dot_all' in FLAGS)
    | re.MULTILINE * ('regex_multiline' in FLAGS)
    | re.IGNORECASE * ('case_insensitive' in FLAGS)
)

EQUAL_FUNC = (  # noqa: E731
    (lambda x, y: str(x).lower() == str(y).lower())
    if 'case_insensitive' in FLAGS
    else (lambda x, y: x == y)
)

OPERATOR_FUNCTIONS: dict[type, Callable] = {
    # comparison operators:
    ast.Eq: EQUAL_FUNC,
    ast.NotEq: lambda x, y: not EQUAL_FUNC(x, y),
    ast.Lt: lambda x, y: x < y,
    ast.LtE: lambda x, y: x <= y,
    ast.Gt: lambda x, y: x > y,
    ast.GtE: lambda x, y: x >= y,
    ast.In: lambda x, y: x in y,
    ast.NotIn: lambda x, y: x not in y,
    # boolean operators:
    ast.And: lambda x, y: x and y,
    ast.Or: lambda x, y: x or y,
    # unary operators:
    ast.Not: lambda x: not x,
    ast.USub: lambda x: -x,
}

FUNCTIONS = {
    'regex_match': partial(
        re.fullmatch if 'regex_full_match' in FLAGS else re.search,
        flags=REGEX_FLAGS
    )
}


def get_value(node):
    match type(node):
        case ast.Constant:
            return node.value
        case ast.List:
            return [get_value(item) for item in node.elts]
        case ast.Dict:
            return {
                get_value(key): get_value(value)
                for key, value in zip(node.keys, node.values)
            }
        case ast.Name:
            return VARIABLES[node.id]
        case ast.Call:
            return FUNCTIONS[node.func.id](*map(get_value, node.args))
        case ast.Compare:
            left = get_value(node.left)
            return all(
                OPERATOR_FUNCTIONS[type(op)](
                    left, left := get_value(right)  # noqa: F841
                )
                for op, right in zip(node.ops, node.comparators)
            )
        case ast.BoolOp:
            return reduce(
                OPERATOR_FUNCTIONS[type(node.op)], map(get_value, node.values)
            )
        case ast.UnaryOp:
            return OPERATOR_FUNCTIONS[type(node.op)](get_value(node.operand))
        case _:
            raise SyntaxError(
                f'Unsupported expression type found: {node.__class__.__name__}'
            )


def evaluate(expression: str):
    # sourcery skip: raise-from-previous-error
    try:
        parsed = ast.parse(expression, mode='eval')
    except Exception:
        raise SyntaxError(f'Cannot parse expression: {expression!r}')
    return get_value(parsed.body)


def main():
    try:
        *conditions, default = evaluate(ARGS['conditions'])
        result = next(
            (
                condition['return']
                for condition in conditions
                if evaluate(condition['condition'])
            ),
            default['else']
        )
        return_results(result)
    except Exception as e:
        return_error(f'Error in If-Elif Transformer: {e}')


if __name__ in ('__main__', 'builtin', 'builtins'):
    main()
