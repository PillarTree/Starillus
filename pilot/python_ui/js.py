"""A small but real JavaScript interpreter for Pilot.

Subset covered: var/let/const with block scope, functions (declarations,
expressions, arrows, closures), objects, arrays, if/else, while, do-while,
for, break/continue, return, throw/try/catch/finally, ternary, assignment
and compound operators, ++/--, template-free string ops, and a DOM bridge
(getElementById, querySelector, innerHTML, style, events, timers, ...).
"""

from __future__ import annotations

import json
import math
import re
import time
import itertools

from .html5 import Node

# ---------------------------------------------------------------------------
# Value model
# ---------------------------------------------------------------------------
class JSNull:
    __slots__ = ()

    def __repr__(self):
        return "null"


class JSUndefined:
    __slots__ = ()

    def __repr__(self):
        return "undefined"


NULL = JSNull()
UNDEF = JSUndefined()


class JSObj:
    __slots__ = ("kind", "props", "arr", "fn", "host", "proto", "name",
                 "js_engine", "js_relayout", "js_box")

    def __init__(self, kind="object", props=None, fn=None, host=None,
                 proto=None, name=""):
        self.kind = kind
        self.props = props if props is not None else {}
        self.arr = []
        self.fn = fn            # python callable or JSFunc
        self.host = host        # python object bridge (Node, document, ...)
        self.proto = proto
        self.name = name


class JSFunc:
    __slots__ = ("params", "body", "env", "arrow", "name", "is_async")

    def __init__(self, params, body, env, arrow=False, name="", is_async=False):
        self.params = params
        self.body = body
        self.env = env
        self.arrow = arrow
        self.name = name
        self.is_async = is_async


class JSGenerator:
    __slots__ = ("func", "scope", "this", "state", "done", "value", "yielded_values", "index", "engine")

    def __init__(self, func, scope, this, engine):
        self.func = func
        self.scope = scope
        self.this = this
        self.engine = engine
        self.state = "suspendedStart"
        self.done = False
        self.value = UNDEF
        self.yielded_values = []
        self.index = 0
        self._collect_yields()

    def _collect_yields(self):
        """Execute the generator body and collect all yield values."""
        # Create a special scope for the generator
        scope = Scope(self.func.env, "function")
        for p, v in zip(self.func.params, []):
            scope.vars[p] = v
        
        # We need to evaluate the body and catch yield expressions
        # For now, we'll do a simple evaluation that collects yields
        # This is a simplified implementation
        try:
            self.engine._eval_generator_body(self.func.body, scope, self.this, self)
        except JSReturn as r:
            pass
        self.done = True

    def next(self, value=UNDEF):
        if self.index < len(self.yielded_values):
            value = self.yielded_values[self.index]
            self.index += 1
            # done is true only when we've gone PAST the last yielded value
            # For JavaScript compatibility, done is false for all explicitly yielded values
            # done becomes true only on the call AFTER the last yielded value
            done = self.index > len(self.yielded_values)
            return make_object(value=value, done=done)
        return make_object(value=UNDEF, done=True)

    def return_(self, value=UNDEF):
        self.index = len(self.yielded_values)
        return make_object(value=value, done=True)

    def throw(self, value):
        self.index = len(self.yielded_values)
        raise JSThrow(value)


class JSThrow(Exception):
    def __init__(self, value):
        super().__init__(str(value))
        self.value = value


class JSReturn(Exception):
    def __init__(self, value):
        super().__init__("return")
        self.value = value


class JSBreak(Exception):
    pass


class JSContinue(Exception):
    pass


def to_number(v):
    if isinstance(v, (int, float)):
        return float(v) if isinstance(v, bool) else v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return 0.0
        try:
            return float(s)
        except ValueError:
            return float("nan")
    if v is NULL:
        return 0.0
    if v is UNDEF:
        return float("nan")
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, JSObj):
        return to_number(to_primitive(v))
    return float("nan")


def to_int(v):
    n = to_number(v)
    if math.isnan(n) or math.isinf(n):
        return 0
    return int(n)


def to_string(v):
    if v is NULL:
        return "null"
    if v is UNDEF:
        return "undefined"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return str(v)
    if isinstance(v, str):
        return v
    if isinstance(v, JSObj):
        if v.kind == "array":
            return ",".join(to_string(x) for x in v.arr)
        if v.kind == "function":
            return "function " + (v.name or "") + "() { [code] }"
        p = v.props.get("toString")
        if isinstance(p, JSObj) and p.kind == "function":
            return "[object Object]"
        return "[object Object]"
    return str(v)


def to_primitive(v):
    if isinstance(v, JSObj):
        return to_string(v)
    return v


def is_truthy(v):
    if v is NULL or v is UNDEF:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0 and not (isinstance(v, float) and math.isnan(v))
    if isinstance(v, str):
        return v != ""
    return True


def loose_eq(a, b):
    if a is NULL and b is UNDEF or a is UNDEF and b is NULL:
        return True
    if a is NULL or a is UNDEF or b is NULL or b is UNDEF:
        return False
    if isinstance(a, bool):
        return loose_eq(to_number(a), b)
    if isinstance(b, bool):
        return loose_eq(a, to_number(b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if isinstance(a, float) and math.isnan(a) or \
                isinstance(b, float) and math.isnan(b):
            return False
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, str):
        return loose_eq(a, to_number(b))
    if isinstance(a, str) and isinstance(b, (int, float)):
        return loose_eq(to_number(a), b)
    if isinstance(a, JSObj):
        return loose_eq(to_primitive(a), b)
    if isinstance(b, JSObj):
        return loose_eq(a, to_primitive(b))
    return a is b


def strict_eq(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    return a is b or a == b


def make_object(**props):
    return JSObj(props=dict(props))


def make_array(items=None):
    o = JSObj(kind="array")
    o.arr = list(items) if items else []
    return o


def make_regexp(pattern, flags):
    o = JSObj(kind="regexp")
    o.props["pattern"] = pattern
    o.props["flags"] = flags
    o.props["global"] = "g" in flags
    o.props["ignoreCase"] = "i" in flags
    o.props["multiline"] = "m" in flags
    o.props["dotAll"] = "s" in flags
    o.props["unicode"] = "u" in flags
    o.props["sticky"] = "y" in flags
    o.props["lastIndex"] = 0
    return o


def make_generator_obj(gen):
    o = JSObj(kind="generator")
    o.props["next"] = make_fn(lambda *args: gen.next(args[0] if args else UNDEF), "next")
    o.props["return"] = make_fn(lambda *args: gen.return_(args[0] if args else UNDEF), "return")
    o.props["throw"] = make_fn(lambda *args: gen.throw(args[0] if args else UNDEF), "throw")
    # Get Symbol.iterator from engine globals
    engine = _ENGINE_HOLDER.get("engine")
    if engine:
        sym = engine.global_scope.vars.get("Symbol")
        if sym and isinstance(sym, JSObj):
            sym_iter = sym.props.get("iterator")
            if sym_iter is not None:
                o.props[sym_iter] = make_fn(lambda: o, "[Symbol.iterator]")
    return o


def make_fn(pyfn, name=""):
    return JSObj(kind="function", fn=pyfn, name=name)


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------
KEYWORDS = {"var", "let", "const", "function", "return", "if", "else",
            "while", "do", "for", "in", "of", "break", "continue", "new", "typeof",
            "this", "true", "false", "null", "undefined", "NaN", "Infinity",
            "throw", "try", "catch", "finally", "class", "extends", "super",
            "async", "await", "yield", "static", "get", "set"}

OPS3 = ["===", "!==", ">>>", "**="]
OPS2 = ["==", "!=", "<=", ">=", "&&", "||", "++", "--", "+=", "-=", "*=",
        "/=", "%=", "=>", "**"]
OPS1 = ["+", "-", "*", "/", "%", "<", ">", "=", "!", "(", ")", "{", "}",
        "[", "]", ",", ";", ".", "?", ":", "&", "|", "^", "~", "<<", ">>",
        "&=", "|=", "^="]


class Tok:
    __slots__ = ("type", "val", "line")

    def __init__(self, type, val, line):
        self.type = type
        self.val = val
        self.line = line


def lex(code):
    tokens = []
    i, n = 0, len(code)
    line = 1
    while i < n:
        ch = code[i]
        if ch in " \t\r":
            i += 1
            continue
        if ch == "\n":
            line += 1
            i += 1
            continue
        if code.startswith("//", i):
            j = code.find("\n", i)
            if j < 0:
                break
            i = j
            continue
        if code.startswith("/*", i):
            j = code.find("*/", i + 2)
            i = j + 2 if j >= 0 else n
            continue
        if ch.isdigit() or (ch == "." and i + 1 < n and code[i + 1].isdigit()):
            j = i
            while j < n and (code[j].isdigit() or code[j] in ".eE+-"):
                if code[j] in "+-" and j > i and code[j - 1] not in "eE":
                    break
                j += 1
            text = code[i:j]
            try:
                if any(c in text for c in ".eE"):
                    tokens.append(Tok("num", float(text), line))
                else:
                    tokens.append(Tok("num", int(text), line))
            except ValueError:
                tokens.append(Tok("num", 0.0, line))
            i = j
            continue
        if ch.isalpha() or ch in "_$":
            j = i
            while j < n and (code[j].isalnum() or code[j] in "_$"):
                j += 1
            word = code[i:j]
            if word in KEYWORDS:
                tokens.append(Tok("kw", word, line))
            else:
                tokens.append(Tok("ident", word, line))
            i = j
            continue
        if ch in "'\"":
            quote = ch
            j = i + 1
            buf = []
            while j < n and code[j] != quote:
                c = code[j]
                if c == "\\" and j + 1 < n:
                    esc = code[j + 1]
                    table = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\",
                             "'": "'", '"': '"', "0": "\0", "b": "\b",
                             "f": "\f"}
                    buf.append(table.get(esc, esc))
                    if esc == "u" and j + 5 < n and code[j + 2:j + 6].isdigit() \
                            and all(cx in "0123456789abcdefABCDEF"
                                    for cx in code[j + 2:j + 6]):
                        buf.append(chr(int(code[j + 2:j + 6], 16)))
                        j += 4
                    j += 2
                else:
                    buf.append(c)
                    j += 1
            tokens.append(Tok("str", "".join(buf), line))
            i = j + 1
            continue
        if ch == "/":
            # Check if this is a regex literal or division operator
            # Look back to find the previous non-whitespace character
            k = i - 1
            while k >= 0 and code[k] in " \t\r\n":
                k -= 1
            prev_char = code[k] if k >= 0 else ""
            # Regex literal can follow: ( { [ ; , ? = | & ^ ! < > + - * % ~ = ! > <
            # But not: identifier, number, ), ], }, string, regex, /, *
            is_regex_context = (i == 0 or prev_char in "({[;:,?=|&^!<>+-*/%~")
            if is_regex_context:
                j = i + 1
                buf = []
                in_class = False
                while j < n:
                    c = code[j]
                    if c == "[":
                        in_class = True
                    elif c == "]":
                        in_class = False
                    elif c == "\\" and j + 1 < n:
                        buf.append(c)
                        j += 1
                        if j < n:
                            buf.append(code[j])
                    elif c == "/" and not in_class:
                        break
                    buf.append(c)
                    j += 1
                if j < n and code[j] == "/":
                    j += 1
                    flags = ""
                    while j < n and code[j] in "gimuy":
                        flags += code[j]
                        j += 1
                    tokens.append(Tok("regex", ("".join(buf), flags), line))
                    i = j
                    continue
        matched = None
        for op in OPS3:
            if code.startswith(op, i):
                matched = op
                break
        if matched is None:
            for op in OPS2:
                if code.startswith(op, i):
                    matched = op
                    break
        if matched is None:
            for op in OPS1:
                if code.startswith(op, i):
                    matched = op
                    break
        if matched:
            if matched in ("==", "!=", "<=", ">=", "&&", "||", "+=", "-=",
                           "*=", "/=", "%=", "**=", "===", "!==", "=>", "<<",
                           ">>", "&=", "|=", "^=", "**", "++", "--"):
                tokens.append(Tok("op", matched, line))
            elif matched in ("+", "-", "*", "/", "%", "<", ">", "!", "&",
                             "|", "^", "~"):
                tokens.append(Tok("op", matched, line))
            elif matched == "=":
                tokens.append(Tok("assign", matched, line))
            else:
                tokens.append(Tok("punct", matched, line))
            i += len(matched)
            continue
        i += 1
    tokens.append(Tok("eof", None, line))
    return tokens


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
class Parser:
    def __init__(self, code):
        self.tokens = lex(code)
        self.pos = 0
        self.strict = False

    def peek(self):
        return self.tokens[self.pos]

    def next(self):
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def expect(self, type=None, val=None, kw=None):
        t = self.next()
        if kw is not None:
            if t.type != "kw" or t.val != kw:
                raise SyntaxError(
                    f"expected '{kw}', got '{t.val}' at line {t.line}")
            return t
        if type and t.type != type:
            raise SyntaxError(f"expected {type}, got {t.type} at line {t.line}")
        if val and t.val != val:
            raise SyntaxError(f"expected '{val}', got '{t.val}' at line {t.line}")
        return t

    def at(self, val):
        t = self.peek()
        return (t.type == "punct" or t.type == "op" or t.type == "assign") \
            and t.val == val

    def at_kw(self, kw):
        t = self.peek()
        return t.type == "kw" and t.val == kw

    def skip_semi(self):
        if self.at(";"):
            self.next()

    # -- statements ------------------------------------------------------
    def parse(self):
        body = []
        # Check for "use strict" directive at the start
        saved_pos = self.pos
        first_stmt = None
        if self.peek().type == "str" and self.peek().val == "use strict":
            self.strict = True
            self.next()
            self.skip_semi()
        while self.peek().type != "eof":
            body.append(self.statement())
        return ("block", body, self.strict)

    def _check_strict_directive(self, body):
        """Check if the first statement is a 'use strict' directive."""
        if body and body[0][0] == "expr" and body[0][1][0] == "str" and body[0][1][1] == "use strict":
            return True
        return False

    def statement(self):
        t = self.peek()
        if t.type == "punct" and t.val == "{":
            return self.block()
        if t.type == "kw":
            if t.val == "var" or t.val == "let" or t.val == "const":
                return self.var_decl()
            if t.val == "if":
                return self.if_stmt()
            if t.val == "while":
                return self.while_stmt()
            if t.val == "do":
                return self.do_stmt()
            if t.val == "for":
                return self.for_stmt()
            if t.val == "function":
                return self.func_decl()
            if t.val == "async":
                self.next()
                return self.async_func_decl()
            if t.val == "class":
                return self.class_decl()
            if t.val == "return":
                self.next()
                e = self.expression() if not self.at(";") and \
                    not self.at("}") and self.peek().type != "eof" else \
                    ("null",)
                self.skip_semi()
                return ("return", e)
            if t.val == "break":
                self.next(); self.skip_semi(); return ("break",)
            if t.val == "continue":
                self.next(); self.skip_semi(); return ("continue",)
            if t.val == "throw":
                self.next()
                e = self.expression()
                self.skip_semi()
                return ("throw", e)
            if t.val == "try":
                return self.try_stmt()
        e = self.expression()
        self.skip_semi()
        return ("expr", e)

    def class_decl(self):
        self.expect(kw="class")
        name = ""
        if self.peek().type == "ident":
            name = self.next().val
        super_class = None
        if self.at_kw("extends"):
            self.next()
            super_class = self.expression()
        self.expect(val="{")
        methods = []
        while not self.at("}"):
            if self.peek().type == "eof":
                break
            t = self.peek()
            if t.type == "kw" and t.val == "static":
                self.next()
                methods.append(("static", self.class_method()))
            elif t.type == "kw" and t.val in ("get", "set"):
                kind = self.next().val
                methods.append((kind, self.class_method()))
            else:
                methods.append(("method", self.class_method()))
        self.expect(val="}")
        return ("var", "var", [(name, ("class", name, super_class, methods))])

    def class_method(self):
        is_async = False
        if self.at_kw("async"):
            self.next()
            is_async = True
        if self.at("*"):
            self.next()
            is_async = True
        name = ""
        t = self.peek()
        if t.type == "ident" or t.type == "str":
            name = self.next().val
        else:
            name = self.expect("ident").val
        if self.at("("):
            params, body = self.func_rest()
            return ("method", name, params, body, is_async)
        if self.at(":"):
            self.next()
            value = self.assignment()
            self.skip_semi()
            return ("field", name, value, is_async)
        if self.at("="):
            self.next()
            value = self.assignment()
            self.skip_semi()
            return ("field", name, value, is_async)
        if self.at(";") or self.at("}") or self.peek().type == "eof":
            return ("field", name, None, is_async)
        raise SyntaxError(f"unexpected token in class body at line {self.peek().line}")

    def block(self):
        self.expect(val="{")
        body = []
        while not self.at("}"):
            if self.peek().type == "eof":
                break
            body.append(self.statement())
        self.expect(val="}")
        return ("block", body)

    def var_decl(self, skip_semi=True):
        kw = self.next().val
        decls = []
        while True:
            name = self.expect("ident").val
            init = None
            if self.at("="):
                self.next()
                init = self.expression()
            decls.append((name, init))
            if self.at(","):
                self.next()
                continue
            break
        if skip_semi:
            self.skip_semi()
        return ("var", kw, decls)

    def if_stmt(self):
        self.expect(kw="if")
        self.expect(val="(")
        cond = self.expression()
        self.expect(val=")")
        then = self.statement()
        els = None
        if self.at_kw("else"):
            self.next()
            els = self.statement()
        return ("if", cond, then, els)

    def while_stmt(self):
        self.expect(kw="while")
        self.expect(val="(")
        cond = self.expression()
        self.expect(val=")")
        body = self.statement()
        return ("while", cond, body, False)

    def do_stmt(self):
        self.expect(kw="do")
        body = self.statement()
        self.expect(kw="while")
        self.expect(val="(")
        cond = self.expression()
        self.expect(val=")")
        self.skip_semi()
        return ("while", cond, body, True)

    def for_stmt(self):
        self.expect(kw="for")
        self.expect(val="(")
        if self.peek().type == "kw" and self.peek().val in ("var", "let",
                                                            "const"):
            kw = self.next().val
            name = self.expect("ident").val
            if self.at_kw("in") or self.at_kw("of"):
                kind = self.next().val
                obj = self.expression()
                self.expect(val=")")
                body = self.statement()
                return ("for" + kind, kw, name, obj, body)
            self.expect(val="=")
            init = ("var", kw, [(name, self.expression())])
        else:
            init = self.expression()
            if self.at_kw("in") or self.at_kw("of"):
                kind = self.next().val
                if init[0] == "ident":
                    name = init[1]
                else:
                    raise SyntaxError("invalid for-in/of left-hand side")
                obj = self.expression()
                self.expect(val=")")
                body = self.statement()
                return ("for" + kind, None, name, obj, body)
        self.expect(val=";")
        cond = None
        if not self.at(";"):
            cond = self.expression()
        self.expect(val=";")
        step = None
        if not self.at(")"):
            step = ("expr", self.expression())
        self.expect(val=")")
        body = self.statement()
        return ("for", init, cond, step, body)

    def func_decl(self):
        is_async = False
        is_generator = False
        if self.at_kw("async"):
            self.next()
            is_async = True
        self.expect(kw="function")
        if self.at("*"):
            self.next()
            is_generator = True
        name = self.expect("ident").val
        params, body = self.func_rest()
        return ("var", "var", [(name, ("func", params, body, name, is_generator, is_async))])

    def async_func_decl(self):
        # async function declaration: async function name() {}
        # The async keyword has already been consumed by the statement parser
        is_async = True
        is_generator = False
        self.expect(kw="function")
        if self.at("*"):
            self.next()
            is_generator = True
        name = self.expect("ident").val
        params, body = self.func_rest()
        return ("var", "var", [(name, ("func", params, body, name, is_generator, is_async))])

    def try_stmt(self):
        self.expect(kw="try")
        body = self.block()
        var_name = None
        catch = None
        if self.at_kw("catch"):
            self.next()
            if self.at("("):
                self.next()
                var_name = self.expect("ident").val
                self.expect(val=")")
            catch = self.block()
        finally_ = None
        if self.at_kw("finally"):
            self.next()
            finally_ = self.block()
        return ("try", body, var_name, catch, finally_)

    def func_rest(self):
        self.expect(val="(")
        params = []
        seen = set()
        while not self.at(")"):
            name = self.expect("ident").val
            if self.strict and name in seen:
                raise SyntaxError(f"Duplicate parameter name '{name}' not allowed in strict mode")
            seen.add(name)
            params.append(name)
            if self.at(","):
                self.next()
        self.expect(val=")")
        body = self.block()
        return params, body

    # -- expressions ------------------------------------------------------
    def expression(self):
        return self.assignment()

    def assignment(self):
        # async arrow functions: async x => e   or   async (a, b) => e
        if self.at_kw("async"):
            self.next()
            t = self.peek()
            if t.type == "ident" and self.tokens[self.pos + 1].type == "op" and \
                    self.tokens[self.pos + 1].val == "=>":
                self.next()
                self.next()
                body = self.arrow_body()
                return ("func", [t.val], body, "", True)
            if t.type == "punct" and t.val == "(" and self._looks_like_arrow():
                self.next()
                params = []
                while not self.at(")"):
                    params.append(self.expect("ident").val)
                    if self.at(","):
                        self.next()
                self.expect(val=")")
                self.expect(val="=>")
                body = self.arrow_body()
                return ("func", params, body, "", True)
        # arrow functions:  x => e   or   (a, b) => e
        t = self.peek()
        if t.type == "ident" and self.tokens[self.pos + 1].type == "op" and \
                self.tokens[self.pos + 1].val == "=>":
            self.next()
            self.next()
            body = self.arrow_body()
            return ("func", [t.val], body, "", False)
        if t.type == "punct" and t.val == "(" and self._looks_like_arrow():
            self.next()
            params = []
            while not self.at(")"):
                params.append(self.expect("ident").val)
                if self.at(","):
                    self.next()
            self.expect(val=")")
            self.expect(val="=>")
            body = self.arrow_body()
            return ("func", params, body, "", False)
        left = self.ternary()
        t = self.peek()
        if t.type == "assign" or (t.type == "op" and t.val.endswith("=") and
                                  t.val != "=>"):
            self.next()
            right = self.assignment()
            return ("assign", t.val, left, right)
        return left

    def _looks_like_arrow(self):
        """True if the parenthesised group starting at pos is arrow params."""
        depth = 0
        i = self.pos
        while i < len(self.tokens):
            tok = self.tokens[i]
            if tok.type == "punct":
                if tok.val == "(":
                    depth += 1
                elif tok.val == ")":
                    depth -= 1
                    if depth == 0:
                        nxt = self.tokens[i + 1]
                        return nxt.type == "op" and nxt.val == "=>"
            elif tok.type == "eof":
                return False
            i += 1
        return False

    def arrow_body(self):
        if self.at("{"):
            return self.block()
        expr = self.expression()
        return ("block", [("return", expr)])

    def ternary(self):
        cond = self.logical_or()
        if self.at("?"):
            self.next()
            then = self.assignment()
            self.expect(val=":")
            els = self.assignment()
            return ("tern", cond, then, els)
        return cond

    def logical_or(self):
        left = self.logical_and()
        while self.at("||"):
            self.next()
            right = self.logical_and()
            left = ("bin", "||", left, right)
        return left

    def logical_and(self):
        left = self.equality()
        while self.at("&&"):
            self.next()
            right = self.equality()
            left = ("bin", "&&", left, right)
        return left

    def equality(self):
        left = self.relational()
        while True:
            t = self.peek()
            if t.type == "op" and t.val in ("==", "!=", "===", "!=="):
                self.next()
                right = self.relational()
                left = ("bin", t.val, left, right)
            else:
                return left

    def relational(self):
        left = self.additive()
        while True:
            t = self.peek()
            if t.type == "op" and t.val in ("<", "<=", ">", ">="):
                self.next()
                right = self.additive()
                left = ("bin", t.val, left, right)
            else:
                return left

    def additive(self):
        left = self.multiplicative()
        while True:
            t = self.peek()
            if t.type == "op" and t.val in ("+", "-"):
                self.next()
                right = self.multiplicative()
                left = ("bin", t.val, left, right)
            else:
                return left

    def multiplicative(self):
        left = self.unary()
        while True:
            t = self.peek()
            if t.type == "op" and t.val in ("*", "/", "%"):
                self.next()
                right = self.unary()
                left = ("bin", t.val, left, right)
            else:
                return left

    def unary(self):
        t = self.peek()
        if t.type == "op" and t.val in ("!", "-", "+", "++", "--", "~"):
            self.next()
            return ("un", t.val, self.unary())
        if t.type == "kw" and t.val == "typeof":
            self.next()
            return ("un", "typeof", self.unary())
        if t.type == "kw" and t.val == "await":
            self.next()
            return ("await", self.unary())
        if t.type == "kw" and t.val == "yield":
            self.next()
            if self.at("*"):
                self.next()
                return ("yield*", self.assignment())
            # Check if next token starts an expression
            nxt = self.peek()
            if nxt.type in ("num", "str", "ident", "kw", "punct", "op") and \
               nxt.val not in (";", "}", ")", ",", "]", "eof"):
                return ("yield", self.assignment())
            return ("yield", ("undef",))
        if t.type == "kw" and t.val == "new":
            self.next()
            callee = self._parse_new_target()
            args = []
            if self.at("("):
                self.next()
                while not self.at(")"):
                    args.append(self.assignment())
                    if self.at(","):
                        self.next()
                self.expect(val=")")
            return ("new", callee, args)
        return self.postfix()

    def _parse_new_target(self):
        """Parse the target of a new expression (without call arguments)."""
        t = self.peek()
        if t.type == "kw" and t.val == "new":
            self.next()
            callee = self._parse_new_target()
            return ("new", callee, [])
        return self._parse_member_expression()

    def _parse_member_expression(self):
        """Parse member expressions (primary, member access, computed member)."""
        e = self.primary()
        while True:
            t = self.peek()
            if t.type == "punct" and t.val == ".":
                self.next()
                name = self.expect("ident").val
                e = ("member", e, name, False)
            elif t.type == "punct" and t.val == "[":
                self.next()
                idx = self.expression()
                self.expect(val="]")
                e = ("member", e, idx, True)
            else:
                return e

    def postfix(self):
        e = self.call()
        while True:
            t = self.peek()
            if t.type == "op" and t.val in ("++", "--"):
                self.next()
                e = ("post", t.val, e)
            else:
                return e

    def call(self):
        e = self.primary()
        while True:
            t = self.peek()
            if t.type == "punct" and t.val == "(":
                self.next()
                args = []
                while not self.at(")"):
                    args.append(self.assignment())
                    if self.at(","):
                        self.next()
                self.expect(val=")")
                e = ("call", e, args)
            elif t.type == "punct" and t.val == ".":
                self.next()
                name = self._expect_property_name()
                e = ("member", e, name, False)
            elif t.type == "punct" and t.val == "[":
                self.next()
                idx = self.expression()
                self.expect(val="]")
                e = ("member", e, idx, True)
            else:
                return e

    def _expect_property_name(self):
        """Accept identifier or keyword as property name."""
        t = self.peek()
        if t.type == "ident":
            self.next()
            return t.val
        if t.type == "kw":
            # Allow keywords as property names (e.g., catch, finally, class)
            self.next()
            return t.val
        raise SyntaxError(f"expected property name, got '{t.val}' at line {t.line}")

    def primary(self):
        t = self.peek()
        if t.type == "num":
            self.next()
            return ("num", t.val)
        if t.type == "str":
            self.next()
            return ("str", t.val)
        if t.type == "regex":
            self.next()
            pattern, flags = t.val
            return ("regex", pattern, flags)
        if t.type == "ident":
            self.next()
            return ("ident", t.val)
        if t.type == "kw":
            if t.val == "true":
                self.next(); return ("bool", True)
            if t.val == "false":
                self.next(); return ("bool", False)
            if t.val == "null":
                self.next(); return ("null",)
            if t.val == "undefined":
                self.next(); return ("undef",)
            if t.val == "NaN":
                self.next(); return ("num", float("nan"))
            if t.val == "Infinity":
                self.next(); return ("num", float("inf"))
            if t.val == "this":
                self.next(); return ("this",)
            if t.val == "super":
                self.next(); return ("super",)
            if t.val == "class":
                self.next()
                name = ""
                if self.peek().type == "ident":
                    name = self.next().val
                super_class = None
                if self.at_kw("extends"):
                    self.next()
                    super_class = self.expression()
                self.expect(val="{")
                methods = []
                while not self.at("}"):
                    if self.peek().type == "eof":
                        break
                    t = self.peek()
                    if t.type == "kw" and t.val == "static":
                        self.next()
                        methods.append(("static", self.class_method()))
                    elif t.type == "kw" and t.val in ("get", "set"):
                        kind = self.next().val
                        methods.append((kind, self.class_method()))
                    else:
                        methods.append(("method", self.class_method()))
                self.expect(val="}")
                return ("class", name, super_class, methods)
            if t.val == "function":
                self.next()
                is_generator = False
                if self.at("*"):
                    self.next()
                    is_generator = True
                name = ""
                if self.peek().type == "ident":
                    name = self.next().val
                params, body = self.func_rest()
                return ("func", params, body, name, is_generator, False)
            if t.val == "async":
                self.next()
                if self.at_kw("function"):
                    self.next()
                    is_generator = False
                    if self.at("*"):
                        self.next()
                        is_generator = True
                    name = ""
                    if self.peek().type == "ident":
                        name = self.next().val
                    params, body = self.func_rest()
                    return ("func", params, body, name, is_generator, True)
        if t.type == "punct":
            if t.val == "(":
                self.next()
                e = self.expression()
                self.expect(val=")")
                return e
            if t.val == "[":
                self.next()
                items = []
                while not self.at("]"):
                    items.append(self.assignment())
                    if self.at(","):
                        self.next()
                self.expect(val="]")
                return ("arr", items)
            if t.val == "{":
                self.next()
                props = []
                while not self.at("}"):
                    k = self.peek()
                    key = None
                    if k.type == "ident":
                        key = k.val
                        self.next()
                        if self.at("("):
                            params, body = self.func_rest()
                            props.append((key, ("func", params, body, key,
                                                False)))
                            if self.at(","):
                                self.next()
                            continue
                    elif k.type == "str":
                        key = k.val
                        self.next()
                    if self.at(":"):
                        self.next()
                        props.append((key, self.assignment()))
                    else:
                        props.append((key, ("ident", key)))
                    if self.at(","):
                        self.next()
                self.expect(val="}")
                return ("obj", props)
        if t.type == "op" and t.val == "=>":
            # arrow with no parens: (not reachable) 
            pass
        raise SyntaxError(f"unexpected token '{t.val}' at line {t.line}")


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------
class Scope:
    __slots__ = ("vars", "parent", "kind")

    def __init__(self, parent=None, kind="function"):
        self.vars = {}
        self.parent = parent
        self.kind = kind

    def get(self, name):
        s = self
        while s is not None:
            if name in s.vars:
                return s.vars[name]
            s = s.parent
        raise NameError(f"{name} is not defined")

    def has(self, name):
        s = self
        while s is not None:
            if name in s.vars:
                return True
            s = s.parent
        return False

    def set(self, name, value, declare=False):
        if declare:
            self.vars[name] = value
            return
        s = self
        while s is not None:
            if name in s.vars:
                s.vars[name] = value
                return
            s = s.parent
        # like browsers: assignment to an undeclared name creates a global
        s = self
        while s.parent is not None:
            s = s.parent
        s.vars[name] = value


class JSEngine:
    def __init__(self, ctx):
        self.ctx = ctx          # browser/tab bridge
        self.global_scope = Scope(None, "global")
        self.globals = JSObj()
        self.timers = []
        self._timer_id = 1
        self.handlers = {}      # id(node) -> {type: [fn,...]}
        self.doc_handlers = {}  # type -> [fn,...] (document/window level)
        self._handler_cache = {}
        self._ws_events = []    # [(wrapper, etype, data)] from ws threads
        self._ws_listeners = {}  # id(wrapper) -> {type: [fn,...]}
        self._ws_ready = {}      # id(wrapper) -> int readyState
        self._ws_conns = {}      # id(wrapper) -> ws.WSConn
        self._microtasks = []   # microtask queue for Promise/async
        self._running_microtasks = False
        _ENGINE_HOLDER["engine"] = self
        self._install_globals()

    # ------------------------------------------------------------------
    # globals
    # ------------------------------------------------------------------
    def _install_globals(self):
        g = self.globals
        self.global_scope.vars["window"] = g
        self.global_scope.vars["globalThis"] = g
        self.global_scope.vars["document"] = self._wrap_document()
        self.global_scope.vars["console"] = self._console()
        self.global_scope.vars["Math"] = self._math()
        self.global_scope.vars["JSON"] = self._json()
        self.global_scope.vars["Date"] = self._date_ctor()
        self.global_scope.vars["String"] = self._string_ctor()
        self.global_scope.vars["Number"] = make_fn(self._number_ctor, "Number")
        self.global_scope.vars["Boolean"] = make_fn(
            lambda x: bool(is_truthy(x)) if x is not UNDEF else False,
            "Boolean")
        self.global_scope.vars["Array"] = self._array_ctor_static()
        self.global_scope.vars["Object"] = self._object_ctor()
        self.global_scope.vars["Error"] = self._error_ctor()
        self.global_scope.vars["Promise"] = self._promise_ctor()
        self.global_scope.vars["RegExp"] = self._regex_ctor()
        self.global_scope.vars["setTimeout"] = make_fn(self._set_timeout,
                                                       "setTimeout")
        self.global_scope.vars["setInterval"] = make_fn(self._set_interval,
                                                        "setInterval")
        self.global_scope.vars["clearTimeout"] = make_fn(self._clear_timer,
                                                         "clearTimeout")
        self.global_scope.vars["clearInterval"] = make_fn(self._clear_timer,
                                                          "clearInterval")
        self.global_scope.vars["alert"] = make_fn(self._alert, "alert")
        self.global_scope.vars["confirm"] = make_fn(self._confirm, "confirm")
        self.global_scope.vars["prompt"] = make_fn(self._prompt, "prompt")
        self.global_scope.vars["WebSocket"] = make_fn(self._ws_ctor,
                                                      "WebSocket")
        self.global_scope.vars["pilotSettings"] = self._pilot_settings()
        self.global_scope.vars["parseInt"] = make_fn(
            lambda s, r=10: to_int(to_number(s)) if r == 10 else
            (int(str(s).strip(), r) if isinstance(s, str) and
             re.match(r"^[+-]?[\dA-Za-z]+$", s.strip()) else float("nan")),
            "parseInt")
        self.global_scope.vars["parseFloat"] = make_fn(
            lambda s: to_number(s), "parseFloat")
        self.global_scope.vars["isNaN"] = make_fn(
            lambda x: isinstance(to_number(x), float) and
            math.isnan(to_number(x)), "isNaN")
        self.global_scope.vars["isFinite"] = make_fn(
            lambda x: math.isfinite(to_number(x)), "isFinite")
        self.global_scope.vars["encodeURIComponent"] = make_fn(
            lambda s: __import__("urllib.parse", fromlist=["parse"]).parse
            .quote(to_string(s), safe=""), "encodeURIComponent")
        self.global_scope.vars["decodeURIComponent"] = make_fn(
            lambda s: __import__("urllib.parse", fromlist=["parse"]).parse
            .unquote(to_string(s)), "decodeURIComponent")
        self.global_scope.vars["undefined"] = UNDEF
        self.global_scope.vars["NaN"] = float("nan")
        self.global_scope.vars["Infinity"] = float("inf")
        g.props["setTimeout"] = self.global_scope.vars["setTimeout"]
        g.props["setInterval"] = self.global_scope.vars["setInterval"]
        g.props["clearTimeout"] = self.global_scope.vars["clearTimeout"]
        g.props["clearInterval"] = self.global_scope.vars["clearInterval"]
        g.props["alert"] = self.global_scope.vars["alert"]
        g.props["confirm"] = self.global_scope.vars["confirm"]
        g.props["prompt"] = self.global_scope.vars["prompt"]
        g.props["WebSocket"] = self.global_scope.vars["WebSocket"]
        g.props["pilotSettings"] = self.global_scope.vars["pilotSettings"]
        g.props["console"] = self.global_scope.vars["console"]
        self.global_scope.vars["print"] = make_fn(
            lambda *args: self.ctx.log(" ".join(to_string(a) for a in args)), "print")
        g.props["print"] = self.global_scope.vars["print"]
        g.props["Math"] = self.global_scope.vars["Math"]
        g.props["JSON"] = self.global_scope.vars["JSON"]
        g.props["Date"] = self.global_scope.vars["Date"]
        g.props["parseInt"] = self.global_scope.vars["parseInt"]
        g.props["parseFloat"] = self.global_scope.vars["parseFloat"]
        g.props["isNaN"] = self.global_scope.vars["isNaN"]
        g.props["isFinite"] = self.global_scope.vars["isFinite"]
        g.props["location"] = self.location_obj()
        g.props["history"] = self._history()
        g.props["navigator"] = self._navigator()
        g.props["innerWidth"] = self.ctx.viewport_w()
        g.props["innerHeight"] = self.ctx.viewport_h()
        g.props["devicePixelRatio"] = 1.0
        g.props["screen"] = make_object(width=self.ctx.viewport_w(),
                                        height=self.ctx.viewport_h())
        self.global_scope.vars["Symbol"] = self._symbol_ctor()
        g.props["Symbol"] = self.global_scope.vars["Symbol"]

    def _symbol_ctor(self):
        sym = JSObj(kind="function")
        def to_sym(desc=None):
            desc = to_string(desc) if desc is not UNDEF else ""
            s = JSObj(kind="symbol")
            s.props["description"] = desc
            s.props["toString"] = make_fn(lambda d=desc: "Symbol(" + d + ")", "toString")
            return s
        sym.fn = lambda *a: to_sym(a[0] if a else UNDEF)
        sym.kind = "function"
        for name in ("iterator", "asyncIterator", "match", "replace", "search",
                     "split", "hasInstance", "isConcatSpreadable", "unscopables",
                     "species", "toPrimitive", "toStringTag"):
            sym.props[name] = to_sym("Symbol." + name)
        return sym

    def _console(self):
        def log(*args):
            self.ctx.log(" ".join(to_string(a) for a in args))
        def warn(*args):
            self.ctx.log("⚠ " + " ".join(to_string(a) for a in args))
        def error(*args):
            self.ctx.log("✖ " + " ".join(to_string(a) for a in args))
        c = JSObj()
        for name, fn in (("log", log), ("info", log), ("warn", warn),
                         ("error", error), ("debug", log),
                         ("trace", log)):
            c.props[name] = make_fn(fn, name)
        return c

    def _math(self):
        m = JSObj()
        m.props.update({
            "PI": math.pi, "E": math.e, "LN2": math.log(2),
            "SQRT2": math.sqrt(2),
            "abs": make_fn(lambda x: abs(to_number(x)), "abs"),
            "ceil": make_fn(lambda x: math.ceil(to_number(x)), "ceil"),
            "floor": make_fn(lambda x: math.floor(to_number(x)), "floor"),
            "round": make_fn(lambda x: round(to_number(x)), "round"),
            "trunc": make_fn(lambda x: int(to_number(x)), "trunc"),
            "sign": make_fn(lambda x: (0 if not x else (1 if x > 0 else -1))
                            if not (isinstance(to_number(x), float) and
                                    math.isnan(to_number(x))) else float("nan"),
                            "sign"),
            "sqrt": make_fn(lambda x: math.sqrt(to_number(x)), "sqrt"),
            "cbrt": make_fn(lambda x: x ** (1 / 3) if x >= 0 else
                            -(-x) ** (1 / 3), "cbrt"),
            "pow": make_fn(lambda a, b: math.pow(to_number(a), to_number(b)),
                           "pow"),
            "exp": make_fn(lambda x: math.exp(to_number(x)), "exp"),
            "log": make_fn(lambda x: math.log(to_number(x)), "log"),
            "log2": make_fn(lambda x: math.log2(to_number(x)), "log2"),
            "log10": make_fn(lambda x: math.log10(to_number(x)), "log10"),
            "sin": make_fn(lambda x: math.sin(to_number(x)), "sin"),
            "cos": make_fn(lambda x: math.cos(to_number(x)), "cos"),
            "tan": make_fn(lambda x: math.tan(to_number(x)), "tan"),
            "asin": make_fn(lambda x: math.asin(to_number(x)), "asin"),
            "acos": make_fn(lambda x: math.acos(to_number(x)), "acos"),
            "atan": make_fn(lambda x: math.atan(to_number(x)), "atan"),
            "atan2": make_fn(lambda a, b: math.atan2(to_number(a),
                                                     to_number(b)), "atan2"),
            "min": make_fn(lambda *a: min((to_number(x) for x in a),
                                          default=0), "min"),
            "max": make_fn(lambda *a: max((to_number(x) for x in a),
                                          default=0), "max"),
            "random": make_fn(lambda: __import__("random",
                                                 fromlist=["random"]).random(),
                              "random"),
        })
        return m

    def _json(self):
        j = JSObj()
        j.props["stringify"] = make_fn(self._json_stringify, "stringify")
        j.props["parse"] = make_fn(self._json_parse, "parse")
        return j

    def _json_stringify(self, *args):
        return _jsonify(args[0]) if args else "undefined"

    def _json_parse(self, *args):
        try:
            return _unjsonify(json.loads(args[0]))
        except Exception:  # noqa: BLE001
            return UNDEF

    def _date_ctor(self):
        def ctor(*args):
            if not args or args[0] is UNDEF:
                return make_date(time.time() * 1000)
            if isinstance(args[0], JSObj) and args[0].kind == "object" and \
                    args[0].host is not None and \
                    args[0].host == "date":
                return args[0]
            if len(args) == 1:
                return make_date(to_number(args[0]))
            t = [to_number(a) for a in args]
            if len(t) >= 6:
                dt = time.mktime((int(t[0]), int(t[1]) + 1, int(t[2]),
                                  int(t[3]), int(t[4]), int(t[5]), 0, 0, -1))
            elif len(t) >= 3:
                dt = time.mktime((int(t[0]), int(t[1]) + 1, int(t[2]),
                                  0, 0, 0, 0, 0, -1))
            else:
                dt = time.time()
            return make_date(dt * 1000)
        o = make_fn(ctor, "Date")
        o.props["now"] = make_fn(lambda: time.time() * 1000, "now")
        o.props["parse"] = make_fn(lambda s: float("nan"), "parse")
        return o

    def _string_ctor(self):
        def ctor(x=UNDEF):
            if isinstance(x, JSObj) and x.kind == "object" and x.host \
                    and x.host == "string":
                return x
            return to_string(x)
        return make_fn(ctor, "String")

    def _number_ctor(self, x=UNDEF):
        if x is UNDEF:
            return 0
        return to_number(x)

    def _array_ctor(self, *args):
        if len(args) == 1 and isinstance(args[0], (int, float)) and \
                args[0] >= 0 and not isinstance(args[0], bool):
            return make_array([UNDEF] * int(args[0]))
        return make_array(list(args))

    def _array_ctor_static(self):
        o = make_fn(self._array_ctor, "Array")
        o.props["isArray"] = make_fn(lambda x: isinstance(x, JSObj) and x.kind == "array", "isArray")
        o.props["from"] = make_fn(self._array_from, "from")
        o.props["of"] = make_fn(self._array_of, "of")
        return o

    def _array_from(self, iterable, mapFn=None, thisArg=None):
        if iterable is UNDEF or iterable is NULL:
            raise TypeError("Array.from requires an iterable")
        if isinstance(iterable, JSObj) and iterable.kind == "array":
            items = iterable.arr
        elif isinstance(iterable, str):
            items = list(iterable)
        elif isinstance(iterable, JSObj) and iterable.host is not None:
            try:
                items = list(iterable.host)
            except TypeError:
                items = []
        else:
            items = []
        if mapFn and isinstance(mapFn, JSObj) and mapFn.kind == "function":
            mapped = []
            for i, x in enumerate(items):
                mapped.append(engine_call(mapFn, [x, i], thisArg or NULL))
            return make_array(mapped)
        return make_array(items)

    def _array_of(self, *args):
        return make_array(list(args))

    def _object_ctor(self):
        o = JSObj()
        o.props["keys"] = make_fn(
            lambda obj: make_array([k for k in _obj_keys(obj)]), "keys")
        o.props["values"] = make_fn(
            lambda obj: make_array([_get(obj, k) for k in _obj_keys(obj)]),
            "values")
        o.props["entries"] = make_fn(
            lambda obj: make_array([make_array([k, _get(obj, k)]) for k in _obj_keys(obj)]),
            "entries")
        o.props["assign"] = make_fn(lambda *a: _object_assign(a), "assign")
        o.props["create"] = make_fn(self._object_create, "create")
        o.props["defineProperty"] = make_fn(self._object_define_property, "defineProperty")
        o.props["defineProperties"] = make_fn(self._object_define_properties, "defineProperties")
        o.props["getOwnPropertyDescriptor"] = make_fn(self._object_get_own_property_descriptor, "getOwnPropertyDescriptor")
        o.props["getOwnPropertyDescriptors"] = make_fn(self._object_get_own_property_descriptors, "getOwnPropertyDescriptors")
        o.props["getOwnPropertyNames"] = make_fn(lambda obj: make_array([k for k in _obj_keys(obj)]), "getOwnPropertyNames")
        o.props["getOwnPropertySymbols"] = make_fn(lambda obj: make_array([]), "getOwnPropertySymbols")
        o.props["getPrototypeOf"] = make_fn(lambda obj: getattr(obj, "proto", NULL) if isinstance(obj, JSObj) else NULL, "getPrototypeOf")
        o.props["setPrototypeOf"] = make_fn(self._object_set_prototype_of, "setPrototypeOf")
        o.props["is"] = make_fn(lambda a, b: a is b, "is")
        o.props["isExtensible"] = make_fn(lambda obj: True, "isExtensible")
        o.props["isFrozen"] = make_fn(lambda obj: False, "isFrozen")
        o.props["isSealed"] = make_fn(lambda obj: False, "isSealed")
        o.props["preventExtensions"] = make_fn(lambda obj: obj, "preventExtensions")
        o.props["seal"] = make_fn(lambda obj: obj, "seal")
        o.props["freeze"] = make_fn(lambda obj: obj, "freeze")
        o.props["fromEntries"] = make_fn(self._object_from_entries, "fromEntries")
        return o

    def _object_create(self, proto, props=None):
        if proto is not NULL and proto is not UNDEF and not isinstance(proto, JSObj):
            raise TypeError("Object prototype may only be an Object or null")
        obj = JSObj(proto=proto if proto is not NULL else None)
        if props and isinstance(props, JSObj):
            for k in _obj_keys(props):
                desc = _get(props, k)
                if isinstance(desc, JSObj):
                    obj.props[k] = _get(desc, "value")
        return obj

    def _object_define_property(self, obj, prop, desc):
        if not isinstance(obj, JSObj):
            raise TypeError("Object.defineProperty called on non-object")
        if isinstance(desc, JSObj):
            val = _get(desc, "value")
            if val is not UNDEF:
                obj.props[to_string(prop)] = val
        return obj

    def _object_define_properties(self, obj, props):
        if not isinstance(obj, JSObj):
            raise TypeError("Object.defineProperties called on non-object")
        if isinstance(props, JSObj):
            for k in _obj_keys(props):
                desc = _get(props, k)
                if isinstance(desc, JSObj):
                    val = _get(desc, "value")
                    if val is not UNDEF:
                        obj.props[k] = val
        return obj

    def _object_get_own_property_descriptor(self, obj, prop):
        if not isinstance(obj, JSObj):
            raise TypeError("Object.getOwnPropertyDescriptor called on non-object")
        prop = to_string(prop)
        if prop in obj.props:
            return make_object(value=obj.props[prop], writable=True, enumerable=True, configurable=True)
        return UNDEF

    def _object_get_own_property_descriptors(self, obj):
        if not isinstance(obj, JSObj):
            raise TypeError("Object.getOwnPropertyDescriptors called on non-object")
        result = JSObj()
        for k in _obj_keys(obj):
            result.props[k] = make_object(value=obj.props[k], writable=True, enumerable=True, configurable=True)
        return result

    def _object_set_prototype_of(self, obj, proto):
        if not isinstance(obj, JSObj):
            raise TypeError("Object.setPrototypeOf called on non-object")
        if proto is not NULL and proto is not UNDEF and not isinstance(proto, JSObj):
            raise TypeError("Object.setPrototypeOf prototype must be an Object or null")
        obj.proto = proto if proto is not NULL else None
        return obj

    def _object_from_entries(self, iterable):
        if iterable is UNDEF or iterable is NULL:
            raise TypeError("Object.fromEntries requires an iterable")
        obj = JSObj()
        if isinstance(iterable, JSObj) and iterable.kind == "array":
            for item in iterable.arr:
                if isinstance(item, JSObj) and item.kind == "array" and len(item.arr) >= 2:
                    obj.props[to_string(item.arr[0])] = item.arr[1]
        return obj

    def _error_ctor(self):
        def ctor(msg=""):
            return make_object(message=to_string(msg),
                               name="Error")
        o = make_fn(ctor, "Error")
        return o

    def _promise_ctor(self):
        def ctor(executor):
            if not isinstance(executor, JSObj) or executor.kind != "function":
                raise TypeError("Promise resolver must be a function")
            state = {"status": "pending", "value": None, "handlers": []}
            def resolve(v):
                if state["status"] != "pending":
                    return
                state["status"] = "fulfilled"
                state["value"] = v
                for h in state["handlers"]:
                    h["onFulfilled"](v)
                state["handlers"] = []
            def reject(v):
                if state["status"] != "pending":
                    return
                state["status"] = "rejected"
                state["value"] = v
                for h in state["handlers"]:
                    h["onRejected"](v)
                state["handlers"] = []
            try:
                executor(resolve, reject)
            except Exception as e:
                reject(e)
            p = JSObj(kind="promise")
            p.props["_state"] = state
            p.props["then"] = make_fn(lambda onF, onR=None: _promise_then(p, onF, onR), "then")
            p.props["catch"] = make_fn(lambda onR: _promise_then(p, None, onR), "catch")
            p.props["finally"] = make_fn(lambda onF: _promise_finally(p, onF), "finally")
            return p
        o = make_fn(ctor, "Promise")
        o.props["resolve"] = make_fn(lambda v=UNDEF: _promise_resolve(v), "resolve")
        o.props["reject"] = make_fn(lambda v=UNDEF: _promise_reject(v), "reject")
        o.props["all"] = make_fn(lambda arr: _promise_all(arr), "all")
        o.props["race"] = make_fn(lambda arr: _promise_race(arr), "race")
        return o

    def _regex_ctor(self):
        def ctor(pattern, flags=None):
            if isinstance(pattern, JSObj) and pattern.kind == "regexp":
                if flags is not UNDEF and flags is not None:
                    raise TypeError("Cannot supply flags when constructing from RegExp")
                return pattern
            p = to_string(pattern) if pattern is not UNDEF else ""
            f = to_string(flags) if flags is not UNDEF and flags is not None else ""
            try:
                re.compile(p, self._regex_flags(f))
            except re.error as e:
                raise SyntaxError(f"Invalid regular expression: {p}: {e}")
            return make_regexp(p, f)
        o = make_fn(ctor, "RegExp")
        o.props["prototype"] = self._regex_proto()
        return o

    def _regex_flags(self, flags):
        f = 0
        if "i" in flags:
            f |= re.IGNORECASE
        if "m" in flags:
            f |= re.MULTILINE
        if "s" in flags:
            f |= re.DOTALL
        return f

    def _regex_proto(self):
        proto = JSObj()
        proto.props["exec"] = make_fn(self._regex_exec, "exec")
        proto.props["test"] = make_fn(self._regex_test, "test")
        proto.props["toString"] = make_fn(self._regex_toString, "toString")
        proto.props["[Symbol.match]"] = make_fn(self._regex_match, "[Symbol.match]")
        proto.props["[Symbol.replace]"] = make_fn(self._regex_replace, "[Symbol.replace]")
        proto.props["[Symbol.search]"] = make_fn(self._regex_search, "[Symbol.search]")
        proto.props["[Symbol.split]"] = make_fn(self._regex_split, "[Symbol.split]")
        return proto

    def _regex_exec(self, this, string):
        if not isinstance(this, JSObj) or this.kind != "regexp":
            raise TypeError("RegExp.prototype.exec called on non-RegExp")
        s = to_string(string)
        pattern = this.props["pattern"]
        flags = this.props["flags"]
        global_flag = "g" in flags
        try:
            rx = re.compile(pattern, self._regex_flags(flags))
        except re.error:
            return NULL
        if global_flag:
            rx.lastIndex = to_int(this.props.get("lastIndex", 0))
        m = rx.search(s)
        if m is None:
            if global_flag:
                this.props["lastIndex"] = 0
            return NULL
        if global_flag:
            this.props["lastIndex"] = m.end()
        result = make_array([m.group(0)] + [m.group(i) if i < len(m.groups()) + 1 else UNDEF for i in range(1, len(m.groups()) + 1)])
        result.props["index"] = m.start()
        result.props["input"] = s
        if m.groups():
            result.props["groups"] = make_object(**{k: v for k, v in m.groupdict().items()})
        return result

    def _regex_test(self, this, string):
        if not isinstance(this, JSObj) or this.kind != "regexp":
            raise TypeError("RegExp.prototype.test called on non-RegExp")
        return self._regex_exec(this, string) is not NULL

    def _regex_toString(self, this):
        if not isinstance(this, JSObj) or this.kind != "regexp":
            raise TypeError("RegExp.prototype.toString called on non-RegExp")
        return "/" + this.props["pattern"] + "/" + this.props["flags"]

    def _regex_match(self, this, string):
        if not isinstance(this, JSObj) or this.kind != "regexp":
            raise TypeError("RegExp.prototype[Symbol.match] called on non-RegExp")
        s = to_string(string)
        pattern = this.props["pattern"]
        flags = this.props["flags"]
        global_flag = "g" in flags
        try:
            rx = re.compile(pattern, self._regex_flags(flags))
        except re.error:
            return NULL
        if not global_flag:
            m = rx.search(s)
            if m is None:
                return NULL
            result = make_array([m.group(0)] + [m.group(i) if i < len(m.groups()) + 1 else UNDEF for i in range(1, len(m.groups()) + 1)])
            result.props["index"] = m.start()
            result.props["input"] = s
            if m.groups():
                result.props["groups"] = make_object(**{k: v for k, v in m.groupdict().items()})
            return result
        matches = []
        for m in rx.finditer(s):
            matches.append(m.group(0))
        if not matches:
            return NULL
        return make_array(matches)

    def _regex_replace(self, this, string, replaceValue):
        if not isinstance(this, JSObj) or this.kind != "regexp":
            raise TypeError("RegExp.prototype[Symbol.replace] called on non-RegExp")
        s = to_string(string)
        pattern = this.props["pattern"]
        flags = this.props["flags"]
        global_flag = "g" in flags
        try:
            rx = re.compile(pattern, self._regex_flags(flags))
        except re.error:
            return s
        if isinstance(replaceValue, JSObj) and replaceValue.kind == "function":
            def repl(m):
                args = [m.group(0)] + [m.group(i) if i < len(m.groups()) + 1 else UNDEF for i in range(1, len(m.groups()) + 1)]
                args.append(m.start())
                args.append(s)
                if m.groups():
                    args.append(make_object(**m.groupdict()))
                return to_string(self.call_js(replaceValue, args, NULL))
            return rx.sub(repl, s) if global_flag else rx.sub(repl, s, 1)
        repl_str = to_string(replaceValue)
        return rx.sub(repl_str, s) if global_flag else rx.sub(repl_str, s, 1)

    def _regex_search(self, this, string):
        if not isinstance(this, JSObj) or this.kind != "regexp":
            raise TypeError("RegExp.prototype[Symbol.search] called on non-RegExp")
        s = to_string(string)
        pattern = this.props["pattern"]
        flags = this.props["flags"]
        try:
            rx = re.compile(pattern, self._regex_flags(flags))
        except re.error:
            return -1
        m = rx.search(s)
        return m.start() if m else -1

    def _regex_split(self, this, string, limit=None):
        if not isinstance(this, JSObj) or this.kind != "regexp":
            raise TypeError("RegExp.prototype[Symbol.split] called on non-RegExp")
        s = to_string(string)
        pattern = this.props["pattern"]
        flags = this.props["flags"]
        global_flag = "g" in flags
        try:
            rx = re.compile(pattern, self._regex_flags(flags))
        except re.error:
            return make_array([s])
        lim = to_int(limit) if limit is not UNDEF and limit is not None else 2**31 - 1
        if lim <= 0:
            return make_array()
        parts = rx.split(s, lim - 1)
        return make_array(parts[:lim])

    def _history(self):
        h = JSObj()
        h.props["back"] = make_fn(lambda: self.ctx.history_back(), "back")
        h.props["forward"] = make_fn(lambda: self.ctx.history_forward(),
                                     "forward")
        h.props["go"] = make_fn(lambda n=0: self.ctx.history_go(to_int(n)),
                                "go")
        return h

    def _navigator(self):
        n = make_object(userAgent="Pilot/1.0 (X11; Linux)",
                        platform="X11", language="en-US", onLine=True,
                        appName="Pilot", product="Gecko",
                        cookieEnabled=True)
        return n

    # -- timers -----------------------------------------------------------
    def _set_timeout(self, fn, ms=0):
        return self._add_timer(fn, to_number(ms), None)

    def _set_interval(self, fn, ms=0):
        return self._add_timer(fn, to_number(ms), to_number(ms))

    def _add_timer(self, fn, ms, interval):
        tid = self._timer_id
        self._timer_id += 1
        self.timers.append({"id": tid, "fn": fn, "at": time.time() + ms / 1000,
                            "interval": interval})
        return tid

    # -- document bridge --------------------------------------------------
    def _wrap_document(self):
        o = JSObj(host="document")
        o.js_engine = self
        o.js_relayout = self.ctx.relayout
        o.js_box = None
        return o

    def location_obj(self):
        o = JSObj(host="location")
        o.js_engine = self
        o.js_relayout = self.ctx.relayout
        o.js_box = None
        return o

    def compile_handler(self, node, attr_name, code):
        return compile_handler(self, node, attr_name, code)

    # -- event dispatch ----------------------------------------------------
    def make_event(self, etype, target, data=None):
        ev = JSObj()
        state = {"prevented": False, "stopped": False}
        ev.props["type"] = etype
        ev.props["target"] = wrap_node(target) if isinstance(target, Node) \
            else target
        ev.props["currentTarget"] = ev.props["target"]
        ev.props["preventDefault"] = make_fn(
            lambda: state.__setitem__("prevented", True), "preventDefault")
        ev.props["stopPropagation"] = make_fn(
            lambda: state.__setitem__("stopped", True), "stopPropagation")
        ev.props["defaultPrevented"] = False
        if data:
            for k, v in data.items():
                ev.props[k] = v
        ev.props["state"] = state
        return ev

    def emit(self, node, etype, data=None):
        """Dispatch an event bubbling from node upward.

        Returns True if the default action should proceed (not prevented).
        """
        ev = self.make_event(etype, node, data)
        state = ev.props["state"]
        n = node
        while n is not None:
            if state["stopped"]:
                break
            ev.props["currentTarget"] = wrap_node(n) if n.is_element else NULL
            fns = list(self.handlers.get(id(n), {}).get(etype, []))
            attr = n.attrs.get("on" + etype) if n.is_element else None
            if attr and attr != "→":
                fn = self.compile_handler(n, "on" + etype, attr)
                if fn:
                    fns.append(fn)
            for fn in fns:
                try:
                    self.call_js(fn, [ev], wrap_node(n))
                except Exception as exc:  # noqa: BLE001
                    self.ctx.log(f"handler error: {exc}")
                if state["stopped"]:
                    break
            n = n.parent
        # document/window-level handlers
        if not state["stopped"]:
            for fn in list(self.doc_handlers.get(etype, [])):
                try:
                    self.call_js(fn, [ev], self._wrap_document())
                except Exception as exc:  # noqa: BLE001
                    self.ctx.log(f"handler error: {exc}")
        return not state["prevented"]

    def emit_dom(self, etype, data=None):
        """Fire a document/window-level event."""
        ev = self.make_event(etype, self._wrap_document(), data)
        state = ev.props["state"]
        for fn in list(self.doc_handlers.get(etype, [])):
            try:
                self.call_js(fn, [ev], self._wrap_document())
            except Exception as exc:  # noqa: BLE001
                self.ctx.log(f"handler error: {exc}")
        return not state["prevented"]

    def _clear_timer(self, tid):
        self.timers = [t for t in self.timers if t["id"] != tid]
        return UNDEF

    # -- WebSocket ----------------------------------------------------------
    def _ws_ctor(self, url=None):
        from . import ws as ws_mod
        url = to_string(url) if url is not UNDEF else ""
        wrapper = JSObj(host="websocket")
        wrapper.js_engine = self
        wrapper.props["url"] = url
        wrapper.props["readyState"] = ws_mod.CONNECTING
        wrapper.props["bufferedAmount"] = 0
        wrapper.props["extensions"] = ""
        wrapper.props["protocol"] = ""
        wrapper.props["send"] = make_fn(
            lambda *a: self._ws_send(wrapper, a[0] if a else UNDEF), "send")
        wrapper.props["close"] = make_fn(
            lambda *a: self._ws_close(wrapper, a[0] if len(a) > 0 else UNDEF,
                                      a[1] if len(a) > 1 else UNDEF), "close")
        wrapper.props["addEventListener"] = make_fn(
            lambda *a: self._ws_add_event_listener(
                wrapper, a[0] if a else "", a[1] if len(a) > 1 else NULL),
            "addEventListener")
        wrapper.props["removeEventListener"] = make_fn(
            lambda *a: self._ws_remove_event_listener(
                wrapper, a[0] if a else "", a[1] if len(a) > 1 else NULL),
            "removeEventListener")
        self._ws_listeners[id(wrapper)] = {}
        conn = None
        error_msg = [None]

        def on_open(c):
            wrapper.props["readyState"] = c.ready_state
            self._ws_events.append((wrapper, "open", {}))

        def on_message(c, text, payload):
            wrapper.props["readyState"] = c.ready_state
            data = text if text is not None else payload
            self._ws_events.append((wrapper, "message", {"data": data}))

        def on_close(c, code, reason):
            wrapper.props["readyState"] = ws_mod.CLOSED
            self._ws_events.append((wrapper, "close",
                                    {"code": code, "reason": reason}))

        def on_error(c, msg):
            error_msg[0] = str(msg)
            wrapper.props["readyState"] = c.ready_state
            self._ws_events.append((wrapper, "error", {}))

        conn = ws_mod.WSConn(url, on_open=on_open, on_message=on_message,
                             on_close=on_close, on_error=on_error)
        self._ws_conns[id(wrapper)] = conn
        self._ws_ready[id(wrapper)] = ws_mod.CONNECTING
        try:
            conn.connect()
        except ws_mod.WSConnectError as exc:
            self._ws_events.append((wrapper, "error", {}))
            self._ws_events.append((wrapper, "close",
                                    {"code": 1006, "reason": str(exc)}))
        return wrapper

    def _ws_send(self, wrapper, msg=None):
        conn = self._ws_conns.get(id(wrapper))
        if conn is None:
            return False
        if msg is UNDEF or msg is NULL:
            msg = ""
        return conn.send(msg)

    def _ws_close(self, wrapper, code=None, reason=None):
        conn = self._ws_conns.get(id(wrapper))
        if conn is None:
            return
        code = to_int(code) if code not in (UNDEF, None) else 1000
        reason = to_string(reason) if reason not in (UNDEF, None) else ""
        conn.close(code, reason[:123])

    def _ws_add_event_listener(self, wrapper, etype, fn):
        lst = self._ws_listeners.setdefault(id(wrapper), {})
        lst.setdefault(to_string(etype), []).append(fn)

    def _ws_remove_event_listener(self, wrapper, etype, fn):
        lst = self._ws_listeners.get(id(wrapper), {})
        fns = lst.get(to_string(etype), [])
        for i, f in enumerate(fns):
            if f is fn:
                del fns[i]
                break

    def _ws_dispatch(self, wrapper, etype, data):
        """Call on* props and addEventListener handlers (main thread)."""
        ev = JSObj()
        ev.props["type"] = etype
        ev.props["target"] = wrapper
        for k, v in data.items():
            ev.props[k] = v
        fn = wrapper.props.get("on" + etype)
        if isinstance(fn, JSObj) and fn.kind == "function":
            try:
                self.call_js(fn, [ev], wrapper)
            except Exception as exc:  # noqa: BLE001
                self.ctx.log(f"ws handler error: {exc}")
        for fn in list(self._ws_listeners.get(id(wrapper), {}).get(etype, [])):
            try:
                self.call_js(fn, [ev], wrapper)
            except Exception as exc:  # noqa: BLE001
                self.ctx.log(f"ws listener error: {exc}")

    # -- pilotSettings -------------------------------------------------------
    def _pilot_settings(self):
        def get(name=None):
            from . import settings as s_mod
            if name is UNDEF or name is NULL:
                return make_object(**s_mod.settings.data)
            return s_mod.settings.get(to_string(name))

        def set(name, value):
            from . import settings as s_mod
            return s_mod.settings.set(to_string(name), value)

        def save():
            from . import settings as s_mod
            s_mod.settings.save()
            s_mod.apply_to_theme()
            return True

        o = JSObj()
        for name, fn in (("get", get), ("set", set), ("save", save)):
            o.props[name] = make_fn(fn, name)
        return o

    def tick(self, now=None):
        """Run due timers and pending websocket events; return True if
        anything ran (page may need repaint)."""
        if now is None:
            now = time.time()
        ran = False
        due = [t for t in self.timers if t["at"] <= now]
        self.timers = [t for t in self.timers if t["at"] > now]
        for t in due:
            try:
                self.call_js(t["fn"], [], NULL)
            except Exception as exc:  # noqa: BLE001
                self.ctx.log(f"timer error: {exc}")
            if t["interval"]:
                t["at"] = now + t["interval"] / 1000
                self.timers.append(t)
            ran = True
        events = self._ws_events
        if events:
            self._ws_events = []
            for wrapper, etype, data in events:
                try:
                    self._ws_dispatch(wrapper, etype, data)
                except Exception as exc:  # noqa: BLE001
                    self.ctx.log(f"ws error: {exc}")
                ran = True
        # Run microtasks
        ran = self._run_microtasks() or ran
        return ran

    def _queue_microtask(self, fn):
        """Queue a microtask to run after the current task."""
        self._microtasks.append(fn)

    def _run_microtasks(self):
        """Run all queued microtasks."""
        if self._running_microtasks or not self._microtasks:
            return False
        self._running_microtasks = True
        ran = False
        try:
            while self._microtasks:
                fn = self._microtasks.pop(0)
                try:
                    fn()
                except Exception as exc:  # noqa: BLE001
                    self.ctx.log(f"microtask error: {exc}")
                ran = True
        finally:
            self._running_microtasks = False
        return ran

    # -- alert/confirm/prompt ----------------------------------------------
    def _alert(self, msg=""):
        self.ctx.ui_alert(to_string(msg))
        return UNDEF

    def _confirm(self, msg=""):
        return self.ctx.ui_confirm(to_string(msg))

    def _prompt(self, msg="", default=""):
        return self.ctx.ui_prompt(to_string(msg), to_string(default))

    # ------------------------------------------------------------------
    # evaluation
    # ------------------------------------------------------------------
    def run(self, code, line=0, name="<script>"):
        try:
            ast = Parser(code).parse()
        except SyntaxError as exc:
            self.ctx.log(f"JS syntax error in {name}:{line} {exc}")
            return UNDEF
        try:
            return self.eval(ast, self.global_scope, NULL)
        except JSThrow as exc:
            self.ctx.log(f"Uncaught: {to_string(exc.value)}")
            return UNDEF
        except Exception as exc:  # noqa: BLE001
            import traceback
            self.ctx.log(f"JS error in {name}:{line}: {exc}")
            traceback.print_exc()
            return UNDEF

    def eval_repl(self, code):
        """Evaluate a devtools console expression; raises on syntax errors."""
        from .js_parser import Parser
        ast = Parser(code).parse()
        return self.eval(ast, self.global_scope, NULL)

    def call_js(self, fn, args, this):
        """Invoke a JS function value (closure or python callback)."""
        if isinstance(fn, JSObj) and fn.kind == "function":
            if isinstance(fn.fn, JSFunc):
                closure = fn.fn
                if closure.is_async:
                    return self._call_async_function(closure, args, this)
                scope = Scope(closure.env, "function")
                for p, v in zip(closure.params, args):
                    scope.vars[p] = v
                if closure.arrow:
                    scope = closure.env
                    for p, v in zip(closure.params, args):
                        scope.vars[p] = v
                try:
                    return self.eval(closure.body, scope, this)
                except JSReturn as r:
                    return r.value
                except JSThrow:
                    raise
            return fn.fn(*(args or []))
        if fn is NULL or fn is UNDEF:
            raise TypeError("not a function")
        if callable(fn):
            return fn(*(args or []))
        raise TypeError(f"{to_string(fn)} is not a function")

    def _call_async_function(self, closure, args, this):
        """Call an async function and return a Promise."""
        scope = Scope(closure.env, "function")
        for p, v in zip(closure.params, args):
            scope.vars[p] = v
        if closure.arrow:
            scope = closure.env
            for p, v in zip(closure.params, args):
                scope.vars[p] = v
        def executor(resolve, reject):
            try:
                result = self.eval(closure.body, scope, this)
                resolve(result)
            except JSReturn as r:
                resolve(r.value)
            except JSThrow as e:
                reject(e.value)
            except Exception as e:
                reject(e)
        return _promise_create(executor)

    def _eval_await(self, node, scope, this):
        """Evaluate an await expression."""
        value = self.eval(node, scope, this)
        # If it's a promise, wait for it to resolve
        if isinstance(value, JSObj) and value.kind == "promise":
            state = value.props.get("_state")
            if state:
                if state["status"] == "fulfilled":
                    return state["value"]
                elif state["status"] == "rejected":
                    raise JSThrow(state["value"])
                else:
                    # pending - in a real implementation this would yield
                    # For now, we'll run the event loop until it resolves
                    # This is a simplified implementation
                    while state["status"] == "pending":
                        self.tick()
                    if state["status"] == "fulfilled":
                        return state["value"]
                    else:
                        raise JSThrow(state["value"])
        return value

    def _eval_generator_body(self, body, scope, this, generator):
        """Evaluate a generator body and collect yield values."""
        # This is a simplified implementation that evaluates the body
        # and collects yield expressions
        for stmt in body[1] if body[0] == "block" else [body]:
            try:
                result = self.eval(stmt, scope, this)
                # Check if the statement was a yield expression
                # Yield expressions are wrapped in expr statements: ('expr', ('yield', ...))
                if stmt[0] == "expr":
                    expr = stmt[1]
                    if expr[0] == "yield":
                        generator.yielded_values.append(result)
                    elif expr[0] == "yield*":
                        # yield* delegates to another generator/iterable
                        if isinstance(result, JSObj) and result.kind == "generator":
                            while not result.props["next"]().props.get("done"):
                                generator.yielded_values.append(result.props["next"]().props.get("value"))
                        elif isinstance(result, JSObj) and result.kind == "array":
                            for item in result.arr:
                                generator.yielded_values.append(item)
                        else:
                            generator.yielded_values.append(result)
                elif stmt[0] == "yield":
                    generator.yielded_values.append(result)
                elif stmt[0] == "yield*":
                    if isinstance(result, JSObj) and result.kind == "generator":
                        while not result.props["next"]().props.get("done"):
                            generator.yielded_values.append(result.props["next"]().props.get("value"))
                    elif isinstance(result, JSObj) and result.kind == "array":
                        for item in result.arr:
                            generator.yielded_values.append(item)
                    else:
                        generator.yielded_values.append(result)
            except JSReturn:
                break
            except JSThrow:
                raise
            except Exception:
                # Continue on other errors
                pass

    def eval(self, node, scope, this):
        op = node[0]
        if op == "block":
            strict = node[2] if len(node) > 2 else False
            old_strict = getattr(self, "_strict", False)
            if strict:
                self._strict = True
            for stmt in node[1]:
                self.eval(stmt, scope, this)
            self._strict = old_strict
            return UNDEF
        if op == "num":
            return node[1]
        if op == "str":
            return node[1]
        if op == "bool":
            return node[1]
        if op == "null":
            return NULL
        if op == "undef":
            return UNDEF
        if op == "this":
            return this
        if op == "ident":
            s = scope
            while s is not None:
                if node[1] in s.vars:
                    return s.vars[node[1]]
                s = s.parent
            g = self.globals.props.get(node[1])
            if g is not None:
                return g
            # window props fallback
            raise NameError(f"{node[1]} is not defined")
        if op == "arr":
            return make_array([self.eval(e, scope, this) for e in node[1]])
        if op == "obj":
            o = JSObj()
            for k, v in node[1]:
                o.props[k] = self.eval(v, scope, this)
            return o
        if op == "regex":
            return make_regexp(node[1], node[2])
        if op == "func":
            params, body, name, is_generator = node[1], node[2], node[3], node[4]
            is_async = node[5] if len(node) > 5 else False
            arrow = False  # generators and function declarations are not arrow functions
            if is_generator:
                return JSObj(kind="generator_function", fn=JSFunc(params, body, scope,
                                                              arrow, name, is_async), name=name)
            return JSObj(kind="function", fn=JSFunc(params, body, scope,
                                                    arrow, name, is_async), name=name)
        if op == "class":
            return self._eval_class(node, scope)
        if op == "super":
            return scope.vars.get("super", UNDEF)
        if op == "yield":
            # Yield expression - return the value of the argument
            # The generator's _eval_generator_body will capture this value
            if node[1] is not None:
                return self.eval(node[1], scope, this)
            return UNDEF
        if op == "yield*":
            # yield* delegates to another generator/iterable
            return self.eval(node[1], scope, this)
        if op == "expr":
            return self.eval(node[1], scope, this)
        if op == "var":
            kw, decls = node[1], node[2]
            if kw == "var":
                for name, init in decls:
                    if name not in scope.vars:
                        scope.vars[name] = UNDEF
                for name, init in decls:
                    if init is not None:
                        scope.vars[name] = self.eval(init, scope, this)
            else:
                block = scope
                while block.kind != "block" and block.kind != "global" \
                        and block.parent is not None:
                    block = block.parent
                for name, init in decls:
                    if init is not None:
                        block.vars[name] = self.eval(init, scope, this)
                    else:
                        block.vars[name] = UNDEF
            return UNDEF
        if op == "assign":
            return self._assign(node, scope, this)
        if op == "bin":
            return self._binop(node, scope, this)
        if op == "un":
            op_ = node[1]
            if op_ == "typeof":
                try:
                    v = self.eval(node[2], scope, this)
                except NameError:
                    return "undefined"
                if v is UNDEF:
                    return "undefined"
                if v is NULL:
                    return "object"
                if isinstance(v, bool):
                    return "boolean"
                if isinstance(v, (int, float)):
                    return "number"
                if isinstance(v, str):
                    return "string"
                if isinstance(v, JSObj):
                    if v.kind == "function":
                        return "function"
                    return "object"
                return "object"
            if op_ == "await":
                return self._eval_await(node[2], scope, this)
            v = self.eval(node[2], scope, this)
            if op_ == "!":
                return not is_truthy(v)
            if op_ == "-":
                return -to_number(v)
            if op_ == "+":
                return to_number(v)
            if op_ == "~":
                return ~to_int(v)
                return "object"
            if op_ == "++":
                self._assign_binop(node[2], "+", 1.0, scope, this)
                return to_number(v)
            if op_ == "--":
                self._assign_binop(node[2], "-", 1.0, scope, this)
                return to_number(v)
        if op == "post":
            v = self.eval(node[2], scope, this)
            if node[1] == "++":
                self._assign_binop(node[2], "+", 1.0, scope, this)
            else:
                self._assign_binop(node[2], "-", 1.0, scope, this)
            return v
        if op == "tern":
            return self.eval(node[2] if is_truthy(self.eval(node[1], scope,
                                                            this)) else node[3],
                             scope, this)
        if op == "member":
            return _get(self.eval(node[1], scope, this),
                        self.eval(node[2], scope, this) if node[3] else node[2],
                        scope, this)
        if op == "call":
            fn = self.eval(node[1], scope, this)
            args = [self.eval(a, scope, this) for a in node[2]]
            t = this
            if node[1][0] == "member":
                t = self.eval(node[1][1], scope, this)
            # Check if this is a super() call
            if node[1][0] == "super":
                # super() calls the parent constructor with current this
                return self._call_super(scope, args, this)
            # Check if calling a generator function
            if isinstance(fn, JSObj) and fn.kind == "generator_function":
                closure = fn.fn
                scope2 = Scope(closure.env, "function")
                for p, v in zip(closure.params, args):
                    scope2.vars[p] = v
                gen = JSGenerator(closure, scope2, t, self)
                return make_generator_obj(gen)
            return self.call_js(fn, args, t)
        if op == "new":
            callee = self.eval(node[1], scope, this)
            args = [self.eval(a, scope, this) for a in node[2]]
            if isinstance(callee, JSObj) and callee.kind == "function":
                if isinstance(callee.fn, JSFunc):
                    closure = callee.fn
                    scope2 = Scope(closure.env, "function")
                    for p, v in zip(closure.params, args):
                        scope2.vars[p] = v
                    proto = callee.props.get("prototype")
                    obj = JSObj(proto=proto)
                    try:
                        self.eval(closure.body, scope2, obj)
                    except JSReturn as r:
                        if isinstance(r.value, JSObj):
                            return r.value
                    return obj
                if callable(callee.fn):
                    r = callee.fn(*args)
                    if isinstance(r, JSObj):
                        return r
                    return make_object()
            raise TypeError("not a constructor")
        if op == "if":
            if is_truthy(self.eval(node[1], scope, this)):
                self.eval(node[2], scope, this)
            elif node[3] is not None:
                self.eval(node[3], scope, this)
            return UNDEF
        if op == "while":
            cond, body, is_do = node[1], node[2], node[3]
            try:
                while True:
                    if not is_do:
                        if not is_truthy(self.eval(cond, scope, this)):
                            break
                    else:
                        is_do = False
                    try:
                        self.eval(body, scope, this)
                    except JSContinue:
                        continue
            except JSBreak:
                pass
            return UNDEF
        if op == "for":
            init, cond, step, body = node[1], node[2], node[3], node[4]
            if init:
                self.eval(init, scope, this)
            try:
                while True:
                    if cond is not None and \
                            not is_truthy(self.eval(cond, scope, this)):
                        break
                    try:
                        self.eval(body, scope, this)
                    except JSContinue:
                        pass
                    if step:
                        self.eval(step, scope, this)
            except JSBreak:
                pass
            return UNDEF
        if op == "forin":
            kw, name, obj_expr, body = node[1], node[2], node[3], node[4]
            obj = self.eval(obj_expr, scope, this)
            if obj is NULL or obj is UNDEF:
                return UNDEF
            keys = []
            if isinstance(obj, JSObj):
                if obj.kind == "array":
                    keys = [str(i) for i in range(len(obj.arr))]
                else:
                    keys = list(obj.props.keys())
            elif isinstance(obj, dict):
                keys = list(obj.keys())
            elif isinstance(obj, str):
                keys = list(range(len(obj)))
            for k in keys:
                loop_scope = Scope(scope, "block")
                loop_scope.vars[name] = k
                try:
                    self.eval(body, loop_scope, this)
                except JSContinue:
                    continue
                except JSBreak:
                    break
            return UNDEF
        if op == "forof":
            kw, name, obj_expr, body = node[1], node[2], node[3], node[4]
            obj = self.eval(obj_expr, scope, this)
            if obj is NULL or obj is UNDEF:
                return UNDEF
            # Get iterator using Symbol.iterator
            iterator = None
            if isinstance(obj, JSObj):
                sym_iter = _get_symbol_iterator()
                if sym_iter is not None:
                    iterator_fn = _get(obj, sym_iter, scope, this)
                    if isinstance(iterator_fn, JSObj) and iterator_fn.kind == "function":
                        iterator = self.call_js(iterator_fn, [], obj)
                if iterator is None:
                    # Fallback for arrays and strings
                    if obj.kind == "array":
                        iterator = _make_array_iterator(obj)
                    elif obj.host is not None and isinstance(obj.host, str):
                        iterator = _make_string_iterator(obj.host)
            elif isinstance(obj, str):
                iterator = _make_string_iterator(obj)
            
            if iterator is None:
                return UNDEF
            
            # Iterate using the iterator protocol
            while True:
                try:
                    result = self.call_js(_get(iterator, "next"), [], iterator)
                except JSThrow as e:
                    raise
                except Exception as e:
                    # If next() throws, stop iteration
                    break
                
                if not isinstance(result, JSObj):
                    break
                
                done = _get(result, "done")
                if is_truthy(done):
                    break
                
                value = _get(result, "value")
                loop_scope = Scope(scope, "block")
                loop_scope.vars[name] = value
                try:
                    self.eval(body, loop_scope, this)
                except JSContinue:
                    continue
                except JSBreak:
                    break
            return UNDEF
        if op == "return":
            raise JSReturn(self.eval(node[1], scope, this))
        if op == "break":
            raise JSBreak()
        if op == "continue":
            raise JSContinue()
        if op == "throw":
            raise JSThrow(self.eval(node[1], scope, this))
        if op == "try":
            body, var_name, catch, finally_ = node[1:5]
            try:
                self.eval(body, scope, this)
            except (JSThrow, Exception) as exc:  # noqa: BLE001
                if catch is None:
                    if finally_:
                        self.eval(finally_, scope, this)
                    if isinstance(exc, JSThrow):
                        raise
                    raise
                if var_name:
                    err = exc.value if isinstance(exc, JSThrow) else \
                        make_object(message=str(exc), name="Error")
                    scope.vars[var_name] = err
                self.eval(catch, scope, this)
            if finally_:
                self.eval(finally_, scope, this)
            return UNDEF
        raise SyntaxError(f"unknown node {op}")

    # -- assignment / operators -------------------------------------------
    def _assign_binop(self, target, op, value, scope, this):
        """target OP= value  (value already numeric where relevant)."""
        if target[0] == "ident":
            name = target[1]
            cur = scope.get(name)
            nv = self._apply_binop(op, cur, value)
            scope.set(name, nv)
            return nv
        if target[0] == "member":
            obj = self.eval(target[1], scope, this)
            key = self.eval(target[2], scope, this) if target[3] else target[2]
            cur = _get(obj, key, scope, this)
            nv = self._apply_binop(op, cur, value)
            _set(obj, key, nv)
            return nv
        self.eval(value, scope, this)
        return value

    def _assign(self, node, scope, this):
        op, target, value = node[1], node[2], node[3]
        val = self.eval(value, scope, this)
        if target[0] == "ident":
            name = target[1]
            if op == "=":
                if getattr(self, "_strict", False):
                    # In strict mode, check if variable is declared
                    s = scope
                    found = False
                    while s is not None:
                        if name in s.vars:
                            found = True
                            break
                        s = s.parent
                    if not found:
                        raise ReferenceError(f"Assignment to undeclared variable '{name}' in strict mode")
                scope.set(name, val)
                return val
            cur = scope.get(name)
            nv = self._apply_binop(op[:-1], cur, val)
            scope.set(name, nv)
            return nv
        if target[0] == "member":
            obj = self.eval(target[1], scope, this)
            key = self.eval(target[2], scope, this) if target[3] else target[2]
            if op == "=":
                _set(obj, key, val)
                return val
            cur = _get(obj, key, scope, this)
            nv = self._apply_binop(op[:-1], cur, val)
            _set(obj, key, nv)
            return nv
        raise SyntaxError("bad assignment target")

    def _apply_binop(self, op, a, b):
        if op == "+":
            if isinstance(a, str) or isinstance(b, str):
                return to_string(a) + to_string(b)
            return to_number(a) + to_number(b)
        if op == "-":
            return to_number(a) - to_number(b)
        if op == "*":
            return to_number(a) * to_number(b)
        if op == "/":
            n = to_number(b)
            if n == 0:
                return float("inf") if to_number(a) > 0 else \
                    (float("-inf") if to_number(a) < 0 else float("nan"))
            return to_number(a) / n
        if op == "%":
            return to_number(a) % to_number(b)
        if op == "**":
            return math.pow(to_number(a), to_number(b))
        raise SyntaxError(f"bad op {op}")

    def _call_super(self, scope, args, this):
        """Call the parent class constructor with the current this."""
        # Find the super class constructor in the scope chain
        super_ctor = None
        s = scope
        while s is not None:
            if "__super_class__" in s.vars:
                super_ctor = s.vars["__super_class__"]
                break
            s = s.parent
        if super_ctor is None or not isinstance(super_ctor, JSObj):
            raise TypeError("super() called outside of class constructor")
        if isinstance(super_ctor.fn, JSFunc):
            closure = super_ctor.fn
            scope2 = Scope(closure.env, "function")
            for p, v in zip(closure.params, args):
                scope2.vars[p] = v
            try:
                self.eval(closure.body, scope2, this)
            except JSReturn as r:
                if isinstance(r.value, JSObj):
                    return r.value
            return this
        if callable(super_ctor.fn):
            return super_ctor.fn(*args)
        raise TypeError("super() constructor is not callable")

    def _eval_class(self, node, scope):
        name, super_expr, methods = node[1], node[2], node[3]
        super_class = self.eval(super_expr, scope, NULL) if super_expr else None
        if super_class is not None and not (isinstance(super_class, JSObj) and super_class.kind == "function"):
            raise TypeError("Super expression must be null or a function")
        class_scope = Scope(scope, "block")
        if super_class:
            class_scope.vars["__super_class__"] = super_class
        proto = JSObj()
        constructor = None
        static_props = {}
        for method in methods:
            kind = method[0]
            if kind == "method":
                m = method[1]
                m_kind, m_name, params, body, is_async = m[0], m[1], m[2], m[3], m[4]
                if m_name == "constructor":
                    constructor = JSFunc(params, body, class_scope, False, name or "constructor")
                else:
                    fn = JSFunc(params, body, class_scope, False, m_name)
                    proto.props[m_name] = JSObj(kind="function", fn=fn, name=m_name)
            elif kind == "static":
                m = method[1]
                inner_kind = m[0]
                if inner_kind == "method":
                    m_kind, m_name, params, body, is_async = m[0], m[1], m[2], m[3], m[4]
                    fn = JSFunc(params, body, class_scope, False, m_name)
                    static_props[m_name] = JSObj(kind="function", fn=fn, name=m_name)
                elif inner_kind == "field":
                    m_kind, m_name, value_expr, is_async = m[0], m[1], m[2], m[3]
                    if value_expr is not None:
                        val = self.eval(value_expr, scope, NULL)
                        static_props[m_name] = val
            elif kind == "get":
                m = method[1]
                m_kind, m_name, params, body, is_async = m[0], m[1], m[2], m[3], m[4]
                fn = JSFunc([], body, class_scope, False, "get " + m_name)
                proto.props[m_name] = make_object(get=JSObj(kind="function", fn=fn, name="get " + m_name))
            elif kind == "set":
                m = method[1]
                m_kind, m_name, params, body, is_async = m[0], m[1], m[2], m[3], m[4]
                fn = JSFunc(params, body, class_scope, False, "set " + m_name)
                if isinstance(proto.props.get(m_name), JSObj) and proto.props[m_name].kind == "object" and "get" in proto.props[m_name].props:
                    proto.props[m_name].props["set"] = JSObj(kind="function", fn=fn, name="set " + m_name)
                else:
                    proto.props[m_name] = make_object(set=JSObj(kind="function", fn=fn, name="set " + m_name))
            elif kind == "field":
                m = method[1]
                m_kind, m_name, value_expr, is_async = m[0], m[1], m[2], m[3]
                if value_expr is not None:
                    val = self.eval(value_expr, scope, NULL)
                    proto.props[m_name] = val
        if constructor is None and super_class:
            constructor = JSFunc([], ("block", []), class_scope, False, name or "constructor")
        if constructor is None:
            constructor = JSFunc([], ("block", []), class_scope, False, name or "constructor")
        cls = JSObj(kind="function", fn=constructor, name=name)
        cls.props["prototype"] = proto
        proto.props["constructor"] = cls
        cls.proto = super_class.props.get("prototype") if super_class else None
        for k, v in static_props.items():
            cls.props[k] = v
        if name:
            class_scope.vars[name] = cls
        return cls

    def _binop(self, node, scope, this):
        if node[1] in ("&&", "||"):
            a = self.eval(node[2], scope, this)
            if node[1] == "&&":
                return a if not is_truthy(a) else self.eval(node[3], scope,
                                                            this)
            return a if is_truthy(a) else self.eval(node[3], scope, this)
        op, a, b = node[1], self.eval(node[2], scope, this), \
            self.eval(node[3], scope, this)
        if op == "+":
            if isinstance(a, str) or isinstance(b, str):
                return to_string(a) + to_string(b)
            return to_number(a) + to_number(b)
        if op == "-":
            return to_number(a) - to_number(b)
        if op == "*":
            return to_number(a) * to_number(b)
        if op == "/":
            n = to_number(b)
            if n == 0:
                return float("inf") if to_number(a) > 0 else \
                    (float("-inf") if to_number(a) < 0 else float("nan"))
            return to_number(a) / n
        if op == "%":
            return to_number(a) % to_number(b)
        if op == "**":
            return math.pow(to_number(a), to_number(b))
        if op == "==":
            return loose_eq(a, b)
        if op == "!=":
            return not loose_eq(a, b)
        if op == "===":
            return strict_eq(a, b)
        if op == "!==":
            return not strict_eq(a, b)
        if op == "<":
            if isinstance(a, str) and isinstance(b, str):
                return a < b
            return to_number(a) < to_number(b)
        if op == "<=":
            if isinstance(a, str) and isinstance(b, str):
                return a <= b
            return to_number(a) <= to_number(b)
        if op == ">":
            if isinstance(a, str) and isinstance(b, str):
                return a > b
            return to_number(a) > to_number(b)
        if op == ">=":
            if isinstance(a, str) and isinstance(b, str):
                return a >= b
            return to_number(a) >= to_number(b)
        if op == "&&":
            if not is_truthy(a):
                return a
            return b
        if op == "||":
            if is_truthy(a):
                return a
            return b
        if op == "&":
            return to_int(a) & to_int(b)
        if op == "|":
            return to_int(a) | to_int(b)
        if op == "^":
            return to_int(a) ^ to_int(b)
        if op == "<<":
            return to_int(a) << to_int(b)
        if op == ">>":
            return to_int(a) >> to_int(b)
        raise SyntaxError(f"bad op {op}")


# ---------------------------------------------------------------------------
# property access helpers
# ---------------------------------------------------------------------------
def _obj_keys(obj):
    if isinstance(obj, JSObj):
        if obj.kind == "array":
            return list(range(len(obj.arr)))
        return list(obj.props.keys())
    return []


def _get(obj, name, scope=None, this=None):
    if obj is NULL or obj is UNDEF:
        raise TypeError("cannot read property of " + to_string(obj))
    if isinstance(obj, JSObj):
        if obj.kind == "array" and name == "length":
            return len(obj.arr)
        # Handle Symbol keys
        if isinstance(name, JSObj) and name.kind == "symbol":
            if name in obj.props:
                return obj.props[name]
        if isinstance(name, str) and name in obj.props:
            return obj.props[name]
        if obj.kind == "array" and isinstance(name, (int, float)) and \
                name >= 0 and int(name) < len(obj.arr):
            return obj.arr[int(name)]
        if obj.host is not None:
            v = host_get(obj.host, name, obj)
            if v is not _MISSING:
                return v
        if obj.proto is not None:
            return _get(obj.proto, name, scope, this)
        if obj.kind == "array":
            if name == "push":
                return _arr_method("push", obj)
            if name == "pop":
                return _arr_method("pop", obj)
            if name == "shift":
                return _arr_method("shift", obj)
            if name == "unshift":
                return _arr_method("unshift", obj)
            if name == "join":
                return _arr_method("join", obj)
            if name == "indexOf":
                return _arr_method("indexOf", obj)
            if name == "lastIndexOf":
                return _arr_method("lastIndexOf", obj)
            if name == "slice":
                return _arr_method("slice", obj)
            if name == "splice":
                return _arr_method("splice", obj)
            if name == "concat":
                return _arr_method("concat", obj)
            if name == "reverse":
                return _arr_method("reverse", obj)
            if name == "sort":
                return _arr_method("sort", obj)
            if name == "forEach":
                return _arr_method("forEach", obj)
            if name == "map":
                return _arr_method("map", obj)
            if name == "filter":
                return _arr_method("filter", obj)
            if name == "reduce":
                return _arr_method("reduce", obj)
            if name == "includes":
                return _arr_method("includes", obj)
            if name == "find":
                return _arr_method("find", obj)
            if name == "findIndex":
                return _arr_method("findIndex", obj)
            if name == "findLast":
                return _arr_method("findLast", obj)
            if name == "findLastIndex":
                return _arr_method("findLastIndex", obj)
            if name == "flat":
                return _arr_method("flat", obj)
            if name == "flatMap":
                return _arr_method("flatMap", obj)
            if name == "toString":
                return make_fn(lambda self=obj: to_string(self), "toString")
            if name == "toLocaleString":
                return _arr_method("toLocaleString", obj)
            if name == "keys":
                return _arr_method("keys", obj)
            if name == "values":
                return _arr_method("values", obj)
            if name == "entries":
                return _arr_method("entries", obj)
            if name == "at":
                return _arr_method("at", obj)
            if name == "copyWithin":
                return _arr_method("copyWithin", obj)
            if name == "fill":
                return _arr_method("fill", obj)
            if name == "every":
                return _arr_method("every", obj)
            if name == "some":
                return _arr_method("some", obj)
            if name == "Symbol.iterator" or name == "[Symbol.iterator]":
                return make_fn(lambda self=obj: _make_array_iterator(self), "[Symbol.iterator]")
            return UNDEF
        if obj.kind == "function":
            if name == "call":
                return make_fn(_fn_call_bind(obj, False), "call")
            if name == "apply":
                return make_fn(_fn_call_bind(obj, True), "apply")
            if name == "bind":
                return make_fn(_fn_bind(obj), "bind")
            return UNDEF
        if obj.kind == "regexp":
            if name == "exec":
                return make_fn(lambda *args: _ENGINE_HOLDER["engine"]._regex_exec(obj, args[0] if args else UNDEF), "exec")
            if name == "test":
                return make_fn(lambda *args: _ENGINE_HOLDER["engine"]._regex_test(obj, args[0] if args else UNDEF), "test")
            if name == "toString":
                return make_fn(lambda: _ENGINE_HOLDER["engine"]._regex_toString(obj), "toString")
            if name in ("[Symbol.match]", "[Symbol.replace]", "[Symbol.search]", "[Symbol.split]"):
                method_name = name[1:-1].replace("Symbol.", "").lower()
                return make_fn(lambda *args: getattr(_ENGINE_HOLDER["engine"], "_regex_" + method_name)(obj, args[0] if args else UNDEF, args[1] if len(args) > 1 else UNDEF), name)
            if name == "source":
                return obj.props["pattern"]
            if name == "flags":
                return obj.props["flags"]
            if name == "global":
                return obj.props["global"]
            if name == "ignoreCase":
                return obj.props["ignoreCase"]
            if name == "multiline":
                return obj.props["multiline"]
            if name == "dotAll":
                return obj.props["dotAll"]
            if name == "unicode":
                return obj.props["unicode"]
            if name == "sticky":
                return obj.props["sticky"]
            if name == "lastIndex":
                return obj.props.get("lastIndex", 0)
            return UNDEF
        return UNDEF
    if isinstance(obj, str):
        m = _string_method(name, obj)
        if m is not _MISSING:
            return m
        if name == "length":
            return len(obj)
        return UNDEF
    if isinstance(obj, (int, float)):
        if name == "toFixed":
            return make_fn(lambda digits=0, self=obj:
                           f"{self:.{int(digits)}f}", "toFixed")
        return UNDEF
    return UNDEF


_MISSING = object()


def host_get(host, name, wrapper):
    """Read a property off a Python host object (Node / document bridge)."""
    if isinstance(host, Node):
        return _node_get(host, name, wrapper)
    if isinstance(host, dict):
        if name in host:
            return host[name]
        return _MISSING
    if isinstance(host, tuple) and host and host[0] == "style":
        return _style_get(host[1], name)
    if host == "document":
        return _document_get(host, name, wrapper)
    if host == "location":
        return _location_get(name, wrapper)
    if name == "toString":
        return make_fn(lambda: "[object]", "toString")
    return _MISSING


def host_set(host, name, value, wrapper):
    if isinstance(host, Node):
        _node_set(host, name, value, wrapper)
    elif isinstance(host, dict):
        host[name] = value
    elif isinstance(host, tuple) and host and host[0] == "style":
        _style_set(host[1], name, value)
        host[1].js_engine.ctx.relayout()
    elif host == "location":
        _location_set(name, value, wrapper)
    elif host == "document":
        _document_set(name, value, wrapper)


# -- document bridge --------------------------------------------------------
def _doc_node(wrapper):
    return wrapper.js_engine.ctx.document_node()


def _document_get(host, name, wrapper):
    engine = wrapper.js_engine
    doc = engine.ctx.document_node()
    if name == "title":
        t = doc.first("title")
        return t.text_content() if t else ""
    if name == "body":
        body = doc.first("body")
        return wrap_node(body) if body else NULL
    if name == "head":
        head = doc.first("head")
        return wrap_node(head) if head else NULL
    if name == "documentElement":
        html = doc.first("html") or doc
        return wrap_node(html)
    if name == "URL" or name == "location":
        if name == "location":
            return engine.location_obj()
        return engine.ctx.base_url()
    if name == "readyState":
        return "complete"
    if name == "cookie":
        return ""
    if name == "hidden":
        return False
    if name == "visibilityState":
        return "visible"
    if name == "referrer":
        return ""
    if name == "characterSet" or name == "charset":
        return "UTF-8"
    if name == "forms":
        return make_array([wrap_node(n) for n in doc.elements()
                           if n.tag_name() == "form"])
    if name == "images":
        return make_array([wrap_node(n) for n in doc.elements()
                           if n.tag_name() == "img"])
    if name == "scripts":
        return make_array([wrap_node(n) for n in doc.elements()
                           if n.tag_name() == "script"])
    if name == "links":
        return make_array([wrap_node(n) for n in doc.elements()
                           if n.tag_name() == "a"])
    m = DOC_METHODS.get(name)
    if m:
        return make_fn(lambda *args, m=m: m(doc, engine, args), name)
    return _MISSING


def _document_set(name, value, wrapper):
    engine = wrapper.js_engine
    if name == "title":
        doc = engine.ctx.document_node()
        t = doc.first("title")
        if t is None:
            head = doc.first("head")
            if head is not None:
                t = Node(tag="title")
                head.append(t)
        if t is not None:
            t.children = [Node(text=to_string(value), is_text=True)]
            for c in t.children:
                c.parent = t
            engine.ctx.title_changed()


def _location_get(name, wrapper):
    engine = wrapper.js_engine
    from urllib.parse import urlparse
    u = urlparse(engine.ctx.base_url())
    if name == "href":
        return engine.ctx.base_url()
    if name == "hash":
        return u.fragment or ""
    if name == "search":
        return u.query or ""
    if name == "pathname":
        return u.path or "/"
    if name == "host":
        return u.netloc
    if name == "hostname":
        return u.hostname or ""
    if name == "port":
        return u.port or ""
    if name == "protocol":
        return u.scheme + ":"
    if name == "origin":
        return u.scheme + "://" + u.netloc
    return _MISSING


def _location_set(name, value, wrapper):
    engine = wrapper.js_engine
    if name == "href":
        engine.ctx.navigate(to_string(value))
    elif name == "hash":
        h = to_string(value)
        if h.startswith("#"):
            engine.ctx.scroll_to_hash(h[1:])
    elif name == "search":
        engine.ctx.navigate(
            engine.ctx.base_url().split("?")[0] + to_string(value))
    elif name == "pathname":
        engine.ctx.navigate(to_string(value))


def _doc_get_element_by_id(doc, engine, args):
    if not args:
        return NULL
    n = doc.find_by_id(to_string(args[0]))
    return wrap_node(n) if n else NULL


def _doc_query_selector(doc, engine, args):
    from .css import matches as _m_match
    if not args:
        return NULL
    sel = to_string(args[0])
    for n in doc.elements():
        if _m_match(n, sel):
            return wrap_node(n)
    return NULL


def _doc_query_selector_all(doc, engine, args):
    from .css import matches as _m_match
    if not args:
        return make_array()
    sel = to_string(args[0])
    return make_array([wrap_node(n) for n in doc.elements()
                       if _m_match(n, sel)])


def _doc_get_elements_by_tag(doc, engine, args):
    tag = to_string(args[0]).lower() if args else ""
    return make_array([wrap_node(n) for n in doc.elements()
                       if n.tag_name() == tag])


def _doc_get_elements_by_class(doc, engine, args):
    cls = to_string(args[0]) if args else ""
    return make_array([wrap_node(n) for n in doc.elements()
                       if cls in n.classes()])


def _doc_get_elements_by_name(doc, engine, args):
    nm = to_string(args[0]) if args else ""
    return make_array([wrap_node(n) for n in doc.elements()
                       if n.get("name") == nm])


def _doc_create_element(doc, engine, args):
    tag = to_string(args[0]).lower() if args else "div"
    node = Node(tag=tag, line=0)
    node.js_engine = engine
    return wrap_node(node)


def _doc_create_text_node(doc, engine, args):
    node = Node(text=to_string(args[0]) if args else "", is_text=True)
    node.js_engine = engine
    o = JSObj(host=node)
    o.js_engine = engine
    o.js_relayout = engine.ctx.relayout
    o.js_box = None
    o.props["__textnode"] = node
    return o


def _doc_write(doc, engine, args):
    text = "".join(to_string(a) for a in args)
    if not text:
        return UNDEF
    body = doc.first("body")
    if body is None:
        return UNDEF
    frag = parse_fragment(text)
    for n in frag:
        n.js_engine = engine
        body.append(n)
    engine.ctx.relayout()
    return UNDEF


def _doc_add_event_listener(doc, engine, args):
    if len(args) < 2:
        return UNDEF
    etype = to_string(args[0]).lower()
    fn = args[1]
    if isinstance(fn, JSObj) and fn.kind == "function":
        engine.doc_handlers.setdefault(etype, []).append(fn)
    return UNDEF


def _doc_remove_event_listener(doc, engine, args):
    if len(args) < 2:
        return UNDEF
    etype = to_string(args[0]).lower()
    fn = args[1]
    lst = engine.doc_handlers.get(etype, [])
    if fn in lst:
        lst.remove(fn)
    return UNDEF


def _doc_focus(doc, engine, args):
    engine.ctx.focus_document()
    return UNDEF


def _doc_has_focus(doc, engine, args):
    return engine.ctx.has_document_focus()


DOC_METHODS = {
    "getElementById": _doc_get_element_by_id,
    "querySelector": _doc_query_selector,
    "querySelectorAll": _doc_query_selector_all,
    "getElementsByTagName": _doc_get_elements_by_tag,
    "getElementsByClassName": _doc_get_elements_by_class,
    "getElementsByName": _doc_get_elements_by_name,
    "createElement": _doc_create_element,
    "createTextNode": _doc_create_text_node,
    "write": _doc_write,
    "writeln": _doc_write,
    "addEventListener": _doc_add_event_listener,
    "removeEventListener": _doc_remove_event_listener,
    "focus": _doc_focus,
    "hasFocus": _doc_has_focus,
    "open": lambda doc, engine, args: UNDEF,
    "close": lambda doc, engine, args: UNDEF,
}


def _node_get(node, name, wrapper):
    if name == "innerHTML":
        return serialize(node)
    if name in ("innerText", "textContent"):
        return node.text_content()
    if name == "value":
        return node.get("value", "")
    if name == "checked":
        return node.get("checked") is not None
    if name == "disabled":
        return node.get("disabled") is not None
    if name == "className":
        return node.get("class", "")
    if name == "id":
        return node.get("id", "")
    if name == "name":
        return node.get("name", "")
    if name == "href":
        return node.get("href", "")
    if name == "src":
        return node.get("src", "")
    if name == "paused" or name == "ended" or name == "seeking" or \
            name == "playing":
        st = wrapper.js_engine.ctx.video_for(node) \
            if node.is_element else None
        if st is None:
            return name == "paused"
        _img, _pos, state, _dur, _err = st.snapshot()
        if name == "paused":
            return state == 0 or state == 2
        if name == "ended":
            return state == 2
        if name == "playing":
            return state == 1
        return False
    if name == "currentTime" or name == "duration" or name == "volume" or \
            name == "readyState" or name == "error":
        st = wrapper.js_engine.ctx.video_for(node) \
            if node.is_element else None
        if st is None:
            return 0.0 if name in ("currentTime", "volume") else \
                (0 if name == "readyState" else NULL)
        _img, pos, state, dur, err = st.snapshot()
        if name == "currentTime":
            return pos
        if name == "duration":
            return dur or float("nan")
        if name == "volume":
            return 1.0
        if name == "readyState":
            return 4 if (_img is not None or state == 2) else 0
        return make_object(code=4 if err else 0)
    if name == "loop":
        return node.get("loop") is not None
    if name == "title":
        return node.get("title", "")
    if name == "placeholder":
        return node.get("placeholder", "")
    if name == "type":
        return node.get("type", "text" if node.tag_name() == "input" else "")
    if name == "style":
        return make_style_obj(node)
    if name == "tagName" or name == "nodeName":
        return node.tag_name().upper()
    if name == "nodeType":
        return 1
    if name == "parentNode" or name == "parentElement":
        return wrap_node(node.parent) if node.parent else NULL
    if name == "firstChild":
        return wrap_node(node.children[0]) if node.children else NULL
    if name == "lastChild":
        return wrap_node(node.children[-1]) if node.children else NULL
    if name == "childNodes":
        return make_array([wrap_node(c) for c in node.children])
    if name == "children":
        return make_array([wrap_node(c) for c in node.children
                           if c.is_element])
    if name == "nextSibling":
        return wrap_node(_sibling(node, 1)) or NULL
    if name == "previousSibling":
        return wrap_node(_sibling(node, -1)) or NULL
    if name == "offsetWidth":
        b = wrapper.js_box
        return b.w if b else 0
    if name == "offsetHeight":
        b = wrapper.js_box
        return b.h if b else 0
    if name == "offsetTop":
        b = wrapper.js_box
        return b.y if b else 0
    if name == "offsetLeft":
        b = wrapper.js_box
        return b.x if b else 0
    if name == "clientWidth":
        b = wrapper.js_box
        return b.w if b else 0
    if name == "clientHeight":
        b = wrapper.js_box
        return b.h if b else 0
    if name == "scrollHeight":
        b = wrapper.js_box
        return b.h if b else 0
    if name == "selectedIndex":
        b = wrapper.js_box
        if b and hasattr(b, "selected_index"):
            return b.selected_index
        return 0
    if name == "options":
        b = wrapper.js_box
        if b and b.options:
            return make_array([make_object(text=t, value=t, selected=i ==
                                           b.selected_index)
                               for i, t in enumerate(b.options)])
        return make_array()
    # event handler attributes
    if name.startswith("on") and _handler_type(name):
        if name in node.attrs:
            h = node.attrs.get(name)
            return wrapper.js_engine.compile_handler(node, name, h)
        return NULL
    # generic attribute
    if name in node.attrs:
        return node.attrs[name]
    # methods
    m = NODE_METHODS.get(name)
    if m:
        return make_fn(lambda *args, m=m, node=node: m(node, args),
                       name)
    return _MISSING


def _handler_type(name):
    return name in ("onclick", "ondblclick", "onchange", "oninput",
                    "onkeydown", "onkeyup", "onkeypress", "onsubmit",
                    "onmouseover", "onmouseout", "onfocus", "onblur",
                    "onload", "onerror", "onscroll", "onmouseenter",
                    "onmouseleave", "onmousedown", "onmouseup", "onkeypress",
                    "ondblclick") or name.startswith("on")


def _sibling(node, delta):
    if node.parent is None:
        return None
    idx = node.parent.children.index(node)
    idx += delta
    if 0 <= idx < len(node.parent.children):
        return node.parent.children[idx]
    return None


def _set(obj, name, value):
    if obj is NULL or obj is UNDEF:
        raise TypeError("cannot set property of " + to_string(obj))
    if isinstance(obj, JSObj):
        if obj.kind == "array":
            if name == "length":
                n = to_int(value)
                obj.arr = obj.arr[:n]
                return
            if isinstance(name, (int, float)):
                i = int(name)
                while len(obj.arr) <= i:
                    obj.arr.append(UNDEF)
                obj.arr[i] = value
                return
        # Handle Symbol keys
        if isinstance(name, JSObj) and name.kind == "symbol":
            obj.props[name] = value
            if obj.host is not None:
                host_set(obj.host, name, value, obj)
            return
        if isinstance(name, str):
            obj.props[name] = value
            if obj.host is not None:
                host_set(obj.host, name, value, obj)
            return
        obj.props[to_string(name)] = value
        return
    raise TypeError("cannot set property of " + to_string(obj))


def _node_set(node, name, value, wrapper):
    if name.startswith("on") and _handler_type(name):
        engine = wrapper.js_engine
        if value is NULL or value is UNDEF or value is False:
            node.attrs.pop(name, None)
            engine.handlers.setdefault(id(node), {})
            engine.handlers[id(node)].pop(_event_type(name), None)
            return
        if isinstance(value, JSObj) and value.kind == "function":
            node.attrs[name] = "→"
            engine.handlers.setdefault(id(node), {}) \
                .setdefault(_event_type(name), []).append(value)
            return
        node.attrs[name] = to_string(value)
        return
    if name == "innerHTML":
        fragment = parse_fragment(to_string(value))
        node.children = fragment
        for c in node.children:
            c.parent = node
            c.js_engine = wrapper.js_engine
        wrapper.js_relayout()
        return
    if name in ("innerText", "textContent"):
        node.children = [Node(text=to_string(value), is_text=True)]
        for c in node.children:
            c.parent = node
            c.js_engine = wrapper.js_engine
        wrapper.js_relayout()
        return
    if name == "value":
        node.set("value", to_string(value))
        wrapper.js_relayout()
        return
    if name == "checked":
        if is_truthy(value):
            node.set("checked", "checked")
        else:
            node.attrs.pop("checked", None)
        wrapper.js_relayout()
        return
    if name == "disabled":
        if is_truthy(value):
            node.set("disabled", "disabled")
        else:
            node.attrs.pop("disabled", None)
        wrapper.js_relayout()
        return
    if name == "className" or name == "class":
        node.set("class", to_string(value))
        wrapper.js_relayout()
        return
    if name == "style":
        if isinstance(value, JSObj):
            # copy style object props into style attribute
            decls = []
            for k, v in value.props.items():
                if v is not UNDEF and v is not NULL:
                    decls.append(f"{_camel_to_dash(k)}: {to_string(v)}")
            node.set("style", "; ".join(decls))
            wrapper.js_relayout()
        else:
            node.set("style", to_string(value))
            wrapper.js_relayout()
        return
    if name in ("id", "name", "href", "src", "title", "placeholder",
                "type", "selected", "multiple", "target", "rel", "alt",
                "for", "action", "method", "rows", "cols", "size", "maxlength",
                "tabindex", "data"):
        node.set(name, to_string(value))
        wrapper.js_relayout()
        return
    if name == "selectedIndex":
        b = wrapper.js_box
        if b and hasattr(b, "selected_index"):
            b.selected_index = to_int(value)
            node.set("_selected_index", str(to_int(value)))
        return
    if name == "currentTime":
        st = wrapper.js_engine.ctx.video_for(node) \
            if node.is_element else None
        if st is not None:
            st.seek(to_number(value))
        return
    if name == "src" and node.is_element and node.tag_name() == "video":
        node.set("src", to_string(value))
        wrapper.js_engine.ctx.video_reload(node)
        wrapper.js_relayout()
        return
    wrapper.js_relayout()


def _camel_to_dash(name):
    return re.sub(r"([A-Z])", lambda m: "-" + m.group(1).lower(), name)


def _event_type(name):
    return name[2:]  # onclick -> click


# -- node methods -----------------------------------------------------------
def _m_append_child(node, args):
    for a in args:
        if isinstance(a, JSObj) and a.host is not None and \
                isinstance(a.host, Node):
            node.append(a.host)
        elif isinstance(a, JSObj) and a.kind == "object" and \
                a.props.get("__textnode"):
            node.append(a.props["__textnode"])
    _engine_for(node).ctx.relayout()
    return args[0] if args else NULL


def _m_remove_child(node, args):
    if args and isinstance(args[0], JSObj) and args[0].host is not None \
            and isinstance(args[0].host, Node):
        args[0].host.remove()
        _engine_for(node).ctx.relayout()
    return args[0] if args else NULL


def _m_remove(node, args):
    node.remove()
    _engine_for(node).ctx.relayout()
    return UNDEF


def _m_insert_before(node, args):
    child, ref = (args + [NULL])[:2]
    cnode = child.host if isinstance(child, JSObj) and \
        isinstance(child.host, Node) else None
    rnode = ref.host if isinstance(ref, JSObj) and \
        isinstance(ref.host, Node) else None
    if cnode is not None:
        if rnode is not None and rnode.parent is node:
            node.insert(node.children.index(rnode), cnode)
        else:
            node.append(cnode)
        _engine_for(node).ctx.relayout()
    return child


def _m_replace_children(node, args):
    node.children = []
    for a in args:
        if isinstance(a, JSObj) and a.host is not None and \
                isinstance(a.host, Node):
            node.append(a.host)
        elif isinstance(a, JSObj) and a.props.get("__textnode"):
            node.append(a.props["__textnode"])
    _engine_for(node).ctx.relayout()
    return UNDEF


def _m_get_attribute(node, args):
    if not args:
        return NULL
    return node.get(args[0], "") if node.get(args[0]) is not None else NULL


def _m_set_attribute(node, args):
    if len(args) >= 2:
        node.set(to_string(args[0]), to_string(args[1]))
        _engine_for(node).ctx.relayout()
    return UNDEF


def _m_has_attribute(node, args):
    return node.get(to_string(args[0]) if args else "") is not None


def _m_remove_attribute(node, args):
    if args:
        node.attrs.pop(to_string(args[0]), None)
        _engine_for(node).ctx.relayout()
    return UNDEF


def _m_query_selector(node, args):
    from .css import matches as _m_match
    if not args:
        return NULL
    sel = to_string(args[0])
    for n in node.elements():
        if n is not node and _m_match(n, sel):
            return wrap_node(n)
    return NULL


def _m_query_selector_all(node, args):
    from .css import matches as _m_match
    if not args:
        return make_array()
    sel = to_string(args[0])
    out = [wrap_node(n) for n in node.elements()
           if n is not node and _m_match(n, sel)]
    return make_array(out)


def _m_get_elements_by_tag(node, args):
    tag = to_string(args[0]).lower() if args else ""
    out = [wrap_node(n) for n in node.elements()
           if n.tag_name() == tag]
    return make_array(out)


def _m_get_elements_by_class(node, args):
    cls = to_string(args[0]) if args else ""
    out = [wrap_node(n) for n in node.elements() if cls in n.classes()]
    return make_array(out)


def _m_matches(node, args):
    from .css import matches as _m_match
    return _m_match(node, to_string(args[0])) if args else False


def _m_closest(node, args):
    from .css import matches as _m_match
    sel = to_string(args[0]) if args else ""
    n = node
    while n is not None:
        if n.is_element and _m_match(n, sel):
            return wrap_node(n)
        n = n.parent
    return NULL


def _m_focus(node, args):
    node.js_engine.ctx.focus_element(node)
    return UNDEF


def _m_blur(node, args):
    node.js_engine.ctx.blur_element(node)
    return UNDEF


def _m_click(node, args):
    node.js_engine.emit(node, "click", {})
    return UNDEF


def _m_scroll_into_view(node, args):
    node.js_engine.ctx.scroll_to(node)
    return UNDEF


def _m_add_event_listener(node, args):
    if len(args) < 2:
        return UNDEF
    etype = to_string(args[0]).lower()
    fn = args[1]
    if isinstance(fn, JSObj) and fn.kind == "function":
        node.js_engine.handlers.setdefault(id(node), {}) \
            .setdefault(etype, []).append(fn)
    return UNDEF


def _m_video_play(node, args):
    st = _engine_for(node).ctx.video_for(node) if node.is_element else None
    if st is not None:
        st.play(_engine_for(node).ctx.browser())
    return UNDEF


def _m_video_pause(node, args):
    st = _engine_for(node).ctx.video_for(node) if node.is_element else None
    if st is not None:
        st.pause()
    return UNDEF


def _m_video_load(node, args):
    st = _engine_for(node).ctx.video_for(node) if node.is_element else None
    if st is not None:
        st.seek(0)
        st.pause()
    return UNDEF


def _m_remove_event_listener(node, args):
    if len(args) < 2:
        return UNDEF
    etype = to_string(args[0]).lower()
    fn = args[1]
    lst = node.js_engine.handlers.get(id(node), {}).get(etype, [])
    if fn in lst:
        lst.remove(fn)
    return UNDEF


NODE_METHODS = {
    "appendChild": _m_append_child,
    "removeChild": _m_remove_child,
    "remove": _m_remove,
    "insertBefore": _m_insert_before,
    "replaceChildren": _m_replace_children,
    "getAttribute": _m_get_attribute,
    "setAttribute": _m_set_attribute,
    "hasAttribute": _m_has_attribute,
    "removeAttribute": _m_remove_attribute,
    "querySelector": _m_query_selector,
    "querySelectorAll": _m_query_selector_all,
    "getElementsByTagName": _m_get_elements_by_tag,
    "getElementsByClassName": _m_get_elements_by_class,
    "matches": _m_matches,
    "closest": _m_closest,
    "focus": _m_focus,
    "blur": _m_blur,
    "click": _m_click,
    "scrollIntoView": _m_scroll_into_view,
    "addEventListener": _m_add_event_listener,
    "removeEventListener": _m_remove_event_listener,
    "play": _m_video_play,
    "pause": _m_video_pause,
    "load": _m_video_load,
}


# -- DOM utilities ----------------------------------------------------------
def _engine_for(node):
    n = node
    while n is not None:
        if getattr(n, "js_engine", None) is not None:
            return n.js_engine
        n = n.parent
    return None


def wrap_node(node):
    if node is None:
        return NULL
    o = JSObj(host=node)
    engine = getattr(node, "js_engine", None) or _engine_for(node)
    o.js_engine = engine
    if engine is not None:
        o.js_relayout = engine.ctx.relayout
        o.js_box = engine.ctx.box_for(node)
    else:
        o.js_relayout = lambda: None
        o.js_box = None
    return o


def serialize(node):
    if node.is_text:
        return node.text
    if node.is_comment:
        return ""
    attrs = "".join(f' {k}="{v}"' for k, v in node.attrs.items()
                    if not k.startswith("_") and k not in ("style",))
    if node.tag_name() in ("script", "style"):
        return f"<{node.tag_name()}{attrs}>{node.text_content()}</{node.tag_name()}>"
    inner = "".join(serialize(c) for c in node.children)
    if node.tag_name() in ("br", "img", "input", "hr", "meta", "link"):
        return f"<{node.tag_name()}{attrs}>"
    return f"<{node.tag_name()}{attrs}>{inner}</{node.tag_name()}>"


def parse_fragment(html):
    """Parse an innerHTML fragment into a list of Nodes."""
    from .html5 import parse as _parse
    doc = _parse(f"<html><body>{html}</body></html>")
    body = doc.first("body")
    return body.children if body else []


def make_style_obj(node):
    o = JSObj(host=("style", node))
    o.js_engine = node.js_engine
    o.js_relayout = node.js_engine.ctx.relayout
    return o


def _style_get(node, name):
    decls = _style_decls(node)
    key = _camel_to_dash(name)
    for k, v in decls:
        if k == key:
            return v
    return ""


def _style_set(node, name, value):
    decls = _style_decls(node)
    key = _camel_to_dash(name)
    if value is UNDEF or value is NULL or value == "":
        decls = [(k, v) for k, v in decls if k != key]
    else:
        found = False
        for i, (k, v) in enumerate(decls):
            if k == key:
                decls[i] = (k, to_string(value))
                found = True
                break
        if not found:
            decls.append((key, to_string(value)))
    node.set("style", "; ".join(f"{k}: {v}" for k, v in decls))


def _style_decls(node):
    out = []
    for part in (node.get("style", "") or "").split(";"):
        if ":" in part:
            k, _, v = part.partition(":")
            out.append((k.strip().lower(), v.strip()))
    return out


def make_date(ms):
    o = JSObj(host="date")
    o.props["ms"] = ms
    o.props["getTime"] = make_fn(lambda: ms, "getTime")
    o.props["valueOf"] = make_fn(lambda: ms, "valueOf")
    o.props["getFullYear"] = make_fn(
        lambda: time.localtime(ms / 1000).tm_year, "getFullYear")
    o.props["getMonth"] = make_fn(
        lambda: time.localtime(ms / 1000).tm_mon - 1, "getMonth")
    o.props["getDate"] = make_fn(
        lambda: time.localtime(ms / 1000).tm_mday, "getDate")
    o.props["getDay"] = make_fn(
        lambda: time.localtime(ms / 1000).tm_wday, "getDay")
    o.props["getHours"] = make_fn(
        lambda: time.localtime(ms / 1000).tm_hour, "getHours")
    o.props["getMinutes"] = make_fn(
        lambda: time.localtime(ms / 1000).tm_min, "getMinutes")
    o.props["getSeconds"] = make_fn(
        lambda: time.localtime(ms / 1000).tm_sec, "getSeconds")
    o.props["getMilliseconds"] = make_fn(
        lambda: int(ms % 1000), "getMilliseconds")
    o.props["toString"] = make_fn(
        lambda: time.strftime("%a %b %d %Y %H:%M:%S",
                              time.localtime(ms / 1000)), "toString")
    o.props["toLocaleString"] = o.props["toString"]
    o.props["toISOString"] = make_fn(
        lambda: time.strftime("%Y-%m-%dT%H:%M:%S.000Z",
                              time.gmtime(ms / 1000)), "toISOString")
    return o


def _jsonify(v, depth=0):
    if depth > 20:
        return "null"
    if v is UNDEF:
        return "null"
    if v is NULL:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        if isinstance(v, float) and math.isnan(v):
            return "null"
        return str(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, JSObj):
        if v.kind == "array":
            return "[" + ",".join(_jsonify(x, depth + 1) for x in v.arr) + "]"
        if v.host is not None:
            return "null"
        parts = []
        for k, val in v.props.items():
            if val is UNDEF or isinstance(val, JSObj) and \
                    val.kind == "function":
                continue
            parts.append(json.dumps(str(k)) + ":" +
                         _jsonify(val, depth + 1))
        return "{" + ",".join(parts) + "}"
    return "null"


def _unjsonify(v):
    if v is None:
        return NULL
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        return v
    if isinstance(v, list):
        return make_array([_unjsonify(x) for x in v])
    if isinstance(v, dict):
        o = JSObj()
        for k, val in v.items():
            o.props[k] = _unjsonify(val)
        return o
    return UNDEF


# -- array methods ----------------------------------------------------------
def _arr_method(name, obj=None):
    def method(*args):
        if obj is None or not isinstance(obj, JSObj) or obj.kind != "array":
            raise TypeError("array method on non-array")
        a = obj.arr
        if name == "push":
            a.extend(args)
            return len(a)
        if name == "pop":
            return a.pop() if a else UNDEF
        if name == "shift":
            return a.pop(0) if a else UNDEF
        if name == "unshift":
            a[0:0] = args
            return len(a)
        if name == "join":
            sep = to_string(args[0]) if args else ","
            return sep.join(to_string(x) for x in a)
        if name == "indexOf":
            target = args[0] if args else UNDEF
            for i, x in enumerate(a):
                if strict_eq(x, target):
                    return i
            return -1
        if name == "lastIndexOf":
            target = args[0] if args else UNDEF
            for i in range(len(a) - 1, -1, -1):
                if strict_eq(a[i], target):
                    return i
            return -1
        if name == "slice":
            start = to_int(args[0]) if args else 0
            end = to_int(args[1]) if len(args) > 1 else len(a)
            return make_array(a[start:end])
        if name == "splice":
            start = to_int(args[0]) if args else 0
            cnt = to_int(args[1]) if len(args) > 1 else len(a) - start
            removed = a[start:start + cnt]
            a[start:start + cnt] = list(args[2:])
            return make_array(removed)
        if name == "concat":
            out = list(a)
            for x in args:
                if isinstance(x, JSObj) and x.kind == "array":
                    out.extend(x.arr)
                else:
                    out.append(x)
            return make_array(out)
        if name == "reverse":
            a.reverse()
            return obj
        if name == "sort":
            if args and isinstance(args[0], JSObj) and \
                    args[0].kind == "function":
                fn = args[0]
                n = len(a)
                for i in range(n):
                    for j in range(0, n - i - 1):
                        c = engine_call(fn, [a[j], a[j + 1]], NULL)
                        if to_number(c) > 0:
                            a[j], a[j + 1] = a[j + 1], a[j]
            else:
                a.sort(key=to_string)
            return obj
        if name == "forEach":
            fn = args[0]
            for i, x in enumerate(list(a)):
                engine_call(fn, [x, i, obj], NULL)
            return UNDEF
        if name == "map":
            fn = args[0]
            out = []
            for i, x in enumerate(a):
                out.append(engine_call(fn, [x, i, obj], NULL))
            return make_array(out)
        if name == "filter":
            fn = args[0]
            out = [x for i, x in enumerate(a)
                   if is_truthy(engine_call(fn, [x, i, obj], NULL))]
            return make_array(out)
        if name == "reduce":
            fn = args[0]
            acc = args[1] if len(args) > 1 else (a[0] if a else UNDEF)
            start = 1 if len(args) < 2 else 0
            for i in range(start, len(a)):
                acc = engine_call(fn, [acc, a[i], i, obj], NULL)
            return acc
        if name == "reduceRight":
            fn = args[0]
            acc = args[1] if len(args) > 1 else (a[-1] if a else UNDEF)
            start = len(a) - 2 if len(args) < 2 else len(a) - 1
            for i in range(start, -1, -1):
                acc = engine_call(fn, [acc, a[i], i, obj], NULL)
            return acc
        if name == "includes":
            target = args[0] if args else UNDEF
            return any(strict_eq(x, target) for x in a)
        if name == "find":
            fn = args[0]
            for i, x in enumerate(a):
                if is_truthy(engine_call(fn, [x, i, obj], NULL)):
                    return x
            return UNDEF
        if name == "findIndex":
            fn = args[0]
            for i, x in enumerate(a):
                if is_truthy(engine_call(fn, [x, i, obj], NULL)):
                    return i
            return -1
        if name == "findLast":
            fn = args[0]
            for i in range(len(a) - 1, -1, -1):
                if is_truthy(engine_call(fn, [a[i], i, obj], NULL)):
                    return a[i]
            return UNDEF
        if name == "findLastIndex":
            fn = args[0]
            for i in range(len(a) - 1, -1, -1):
                if is_truthy(engine_call(fn, [a[i], i, obj], NULL)):
                    return i
            return -1
        if name == "flat":
            depth = to_int(args[0]) if args else 1
            def flatten(arr, d):
                result = []
                for x in arr:
                    if isinstance(x, JSObj) and x.kind == "array" and d > 0:
                        result.extend(flatten(x.arr, d - 1))
                    else:
                        result.append(x)
                return result
            return make_array(flatten(a, depth))
        if name == "flatMap":
            fn = args[0]
            mapped = []
            for i, x in enumerate(a):
                mapped.append(engine_call(fn, [x, i, obj], NULL))
            def flatten(arr, d):
                result = []
                for x in arr:
                    if isinstance(x, JSObj) and x.kind == "array" and d > 0:
                        result.extend(flatten(x.arr, d - 1))
                    else:
                        result.append(x)
                return result
            return make_array(flatten(mapped, 1))
        if name == "toString":
            return ",".join(to_string(x) for x in a)
        if name == "toLocaleString":
            return ",".join(to_string(x) for x in a)
        if name == "keys":
            return make_array(list(range(len(a))))
        if name == "values":
            return make_array(a[:])
        if name == "entries":
            return make_array([make_array([i, a[i]]) for i in range(len(a))])
        if name == "at":
            idx = to_int(args[0]) if args else 0
            if idx < 0:
                idx += len(a)
            return a[idx] if 0 <= idx < len(a) else UNDEF
        if name == "copyWithin":
            target = to_int(args[0]) if args else 0
            start = to_int(args[1]) if len(args) > 1 else 0
            end = to_int(args[2]) if len(args) > 2 else len(a)
            if target < 0: target += len(a)
            if start < 0: start += len(a)
            if end < 0: end += len(a)
            target = max(0, min(target, len(a)))
            start = max(0, min(start, len(a)))
            end = max(start, min(end, len(a)))
            copied = a[start:end]
            for i, v in enumerate(copied):
                if target + i < len(a):
                    a[target + i] = v
            return obj
        if name == "fill":
            value = args[0] if args else UNDEF
            start = to_int(args[1]) if len(args) > 1 else 0
            end = to_int(args[2]) if len(args) > 2 else len(a)
            if start < 0: start += len(a)
            if end < 0: end += len(a)
            start = max(0, min(start, len(a)))
            end = max(start, min(end, len(a)))
            for i in range(start, end):
                a[i] = value
            return obj
        if name == "every":
            fn = args[0]
            for i, x in enumerate(a):
                if not is_truthy(engine_call(fn, [x, i, obj], NULL)):
                    return False
            return True
        if name == "some":
            fn = args[0]
            for i, x in enumerate(a):
                if is_truthy(engine_call(fn, [x, i, obj], NULL)):
                    return True
            return False
        return UNDEF
    return make_fn(method, name)


def _get_symbol_iterator():
    """Get Symbol.iterator from the engine's globals."""
    engine = _ENGINE_HOLDER.get("engine")
    if engine:
        sym = engine.global_scope.vars.get("Symbol")
        if sym and isinstance(sym, JSObj):
            return sym.props.get("iterator")
    return None


def _make_array_iterator(arr):
    """Create an iterator object for an array."""
    if not isinstance(arr, JSObj) or arr.kind != "array":
        raise TypeError("Array iterator requires an array")
    index = 0
    array = arr.arr
    def next_fn():
        nonlocal index
        if index < len(array):
            value = array[index]
            index += 1
            return make_object(value=value, done=False)
        return make_object(value=UNDEF, done=True)
    def return_fn(value=UNDEF):
        nonlocal index
        index = len(array)
        return make_object(value=value, done=True)
    def throw_fn(value):
        nonlocal index
        index = len(array)
        raise JSThrow(value)
    it = JSObj(kind="iterator")
    it.props["next"] = make_fn(next_fn, "next")
    it.props["return"] = make_fn(return_fn, "return")
    it.props["throw"] = make_fn(throw_fn, "throw")
    sym_iter = _get_symbol_iterator()
    if sym_iter is not None:
        it.props[sym_iter] = make_fn(lambda: it, "[Symbol.iterator]")
    return it


def _make_string_iterator(s):
    """Create an iterator object for a string."""
    index = 0
    string = s
    def next_fn():
        nonlocal index
        if index < len(string):
            value = string[index]
            index += 1
            return make_object(value=value, done=False)
        return make_object(value=UNDEF, done=True)
    def return_fn(value=UNDEF):
        nonlocal index
        index = len(string)
        return make_object(value=value, done=True)
    def throw_fn(value):
        nonlocal index
        index = len(string)
        raise JSThrow(value)
    it = JSObj(kind="iterator")
    it.props["next"] = make_fn(next_fn, "next")
    it.props["return"] = make_fn(return_fn, "return")
    it.props["throw"] = make_fn(throw_fn, "throw")
    sym_iter = _get_symbol_iterator()
    if sym_iter is not None:
        it.props[sym_iter] = make_fn(lambda: it, "[Symbol.iterator]")
    return it


_ENGINE_HOLDER = {"engine": None}


def engine_call(fn, args, this):
    """Call a JS function from a method needing the engine."""
    if isinstance(fn, JSObj) and fn.kind == "function" and \
            isinstance(fn.fn, JSFunc):
        closure = fn.fn
        scope = Scope(closure.env, "function")
        for p, v in zip(closure.params, args):
            scope.vars[p] = v
        if closure.arrow:
            scope = closure.env
            for p, v in zip(closure.params, args):
                scope.vars[p] = v
        try:
            return _ENGINE_HOLDER["engine"].eval(closure.body, scope, this)
        except JSReturn as r:
            return r.value
    if isinstance(fn, JSObj) and fn.kind == "function":
        return fn.fn(*(args or []))
    raise TypeError("not a function")


def _fn_call_bind(fn, is_apply):
    def call(*args):
        this = args[0] if args else NULL
        rest = args[1:]
        if is_apply and rest and isinstance(rest[0], JSObj) and \
                rest[0].kind == "array":
            rest = list(rest[0].arr)
        return engine_call(fn, rest, this)
    return call


def _fn_bind(fn):
    def bind(*args):
        this = args[0] if args else NULL
        bound = list(args[1:])
        def caller(*rest):
            return engine_call(fn, bound + list(rest), this)
        o = JSObj(kind="function", fn=caller, name="bound")
        return o
    return bind


def _object_assign(args):
    if not args:
        return make_object()
    target = args[0]
    if not isinstance(target, JSObj):
        target = make_object()
    for src in args[1:]:
        if isinstance(src, JSObj):
            for k, v in src.props.items():
                target.props[k] = v
    return target


# -- string methods ---------------------------------------------------------
def _string_method(name, s):
    if name == "toUpperCase":
        return make_fn(lambda: s.upper(), name)
    if name == "toLowerCase":
        return make_fn(lambda: s.lower(), name)
    if name == "charAt":
        return make_fn(lambda i=0: s[to_int(i)] if 0 <= to_int(i) < len(s)
                       else "", name)
    if name == "charCodeAt":
        return make_fn(lambda i=0: ord(s[to_int(i)]) if
                       0 <= to_int(i) < len(s) else float("nan"), name)
    if name == "codePointAt":
        return make_fn(lambda i=0: ord(s[to_int(i)]) if
                       0 <= to_int(i) < len(s) else UNDEF, name)
    if name == "indexOf":
        return make_fn(lambda sub="", start=0:
                       s.find(to_string(sub), to_int(start)), name)
    if name == "lastIndexOf":
        return make_fn(lambda sub="", start=999999:
                       s.rfind(to_string(sub), 0, to_int(start)), name)
    if name == "includes":
        return make_fn(lambda sub="", start=0:
                       to_string(sub) in s[to_int(start):], name)
    if name == "startsWith":
        return make_fn(lambda sub="", start=0:
                       s[to_int(start):].startswith(to_string(sub)), name)
    if name == "endsWith":
        return make_fn(lambda sub="", length=len(s):
                       s[:to_int(length)].endswith(to_string(sub)), name)
    if name == "substring":
        return make_fn(lambda a=0, b=999999:
                       s[to_int(a):to_int(b)], name)
    if name == "slice":
        return make_fn(lambda a=0, b=999999:
                       s[to_int(a):to_int(b)] if to_int(b) >= 0 else
                       s[to_int(a):], name)
    if name == "split":
        return make_fn(lambda sep="", limit=999999:
                       make_array([to_string(x) for x in
                                   s.split(to_string(sep),
                                           int(limit))]) if sep != "" else
                       make_array(list(s)), name)
    if name == "trim":
        return make_fn(lambda: s.strip(), name)
    if name == "trimStart":
        return make_fn(lambda: s.lstrip(), name)
    if name == "trimEnd":
        return make_fn(lambda: s.rstrip(), name)
    if name == "replace":
        return make_fn(lambda a, b: _js_replace(s, a, b), name)
    if name == "replaceAll":
        return make_fn(lambda a, b: s.replace(to_string(a), to_string(b)), name)
    if name == "repeat":
        return make_fn(lambda n=0: s * max(0, to_int(n)), name)
    if name == "padStart":
        return make_fn(lambda n=0, ch=" ": s.rjust(to_int(n), to_string(ch) or " "),
                       name)
    if name == "padEnd":
        return make_fn(lambda n=0, ch=" ": s.ljust(to_int(n), to_string(ch) or " "),
                       name)
    if name == "concat":
        return make_fn(lambda *a: s + "".join(to_string(x) for x in a),
                       name)
    if name == "match":
        return make_fn(lambda rx: _string_match(s, rx), name)
    if name == "matchAll":
        return make_fn(lambda rx: _string_match_all(s, rx), name)
    if name == "search":
        return make_fn(lambda rx: _string_search(s, rx), name)
    if name == "split":
        return make_fn(lambda sep="", limit=999999:
                       _string_split(s, sep, limit), name)
    if name == "toLocaleLowerCase":
        return make_fn(lambda: s.lower(), name)
    if name == "toLocaleUpperCase":
        return make_fn(lambda: s.upper(), name)
    if name == "at":
        return make_fn(lambda i=0: s[to_int(i)] if -len(s) <= to_int(i) < len(s)
                       else UNDEF, name)
    if name == "Symbol.iterator" or name == "[Symbol.iterator]":
        return make_fn(lambda self=s: _make_string_iterator(self), "[Symbol.iterator]")
    return _MISSING


def _js_replace(s, a, b):
    if isinstance(a, str):
        return s.replace(a, to_string(b))
    return s


def _string_match(s, rx):
    if isinstance(rx, JSObj) and rx.kind == "regexp":
        engine = _ENGINE_HOLDER["engine"]
        if engine:
            return engine._regex_match(rx, s)
        return NULL
    try:
        rx_obj = re.compile(to_string(rx))
        m = rx_obj.search(s)
        if m:
            result = make_array([m.group(0)])
            result.props["index"] = m.start()
            result.props["input"] = s
            return result
    except re.error:
        pass
    return NULL


def _string_match_all(s, rx):
    if isinstance(rx, JSObj) and rx.kind == "regexp":
        engine = _ENGINE_HOLDER["engine"]
        if engine:
            rx2 = JSObj(kind="regexp")
            rx2.props["pattern"] = rx.props["pattern"]
            rx2.props["flags"] = rx.props["flags"] + "g"
            return engine._regex_match(rx2, s)
    try:
        rx_obj = re.compile(to_string(rx) + "g" if "g" not in to_string(rx) else to_string(rx))
        matches = []
        for m in rx_obj.finditer(s):
            matches.append(m.group(0))
        if not matches:
            return NULL
        return make_array(matches)
    except re.error:
        pass
    return NULL


def _string_search(s, rx):
    if isinstance(rx, JSObj) and rx.kind == "regexp":
        engine = _ENGINE_HOLDER["engine"]
        if engine:
            return engine._regex_search(rx, s)
    try:
        rx_obj = re.compile(to_string(rx))
        m = rx_obj.search(s)
        return m.start() if m else -1
    except re.error:
        return -1


def _string_split(s, sep, limit):
    lim = to_int(limit)
    if lim <= 0:
        return make_array()
    if isinstance(sep, JSObj) and sep.kind == "regexp":
        engine = _ENGINE_HOLDER["engine"]
        if engine:
            return engine._regex_split(sep, s, limit)
    if sep == "":
        return make_array(list(s)[:lim])
    parts = s.split(to_string(sep), lim - 1)
    return make_array(parts[:lim])


def _promise_then(promise, onFulfilled, onRejected):
    state = promise.props.get("_state")
    if not state:
        return _promise_reject("Not a promise")
    def make_promise(resolve, reject):
        def handle_fulfilled(v):
            try:
                engine = _ENGINE_HOLDER.get("engine")
                if onFulfilled and isinstance(onFulfilled, JSObj) and onFulfilled.kind == "function":
                    result = engine.call_js(onFulfilled, [v], UNDEF)
                    if isinstance(result, JSObj) and result.props.get("_state"):
                        # result is a promise
                        result.props["then"](resolve, reject)
                    else:
                        resolve(result)
                else:
                    resolve(v)
            except Exception as e:
                reject(e)
        def handle_rejected(v):
            try:
                engine = _ENGINE_HOLDER.get("engine")
                if onRejected and isinstance(onRejected, JSObj) and onRejected.kind == "function":
                    result = engine.call_js(onRejected, [v], UNDEF)
                    if isinstance(result, JSObj) and result.props.get("_state"):
                        result.props["then"](resolve, reject)
                    else:
                        resolve(result)
                else:
                    reject(v)
            except Exception as e:
                reject(e)
        
        def queue_handler(handler, value):
            engine = _ENGINE_HOLDER.get("engine")
            if engine:
                engine._queue_microtask(lambda: handler(value))
            else:
                handler(value)
        
        if state["status"] == "fulfilled":
            queue_handler(handle_fulfilled, state["value"])
        elif state["status"] == "rejected":
            queue_handler(handle_rejected, state["value"])
        else:
            state["handlers"].append({"onFulfilled": handle_fulfilled, "onRejected": handle_rejected})
    return _promise_create(make_promise)


def _promise_finally(promise, onFinally):
    state = promise.props.get("_state")
    if not state:
        return _promise_reject("Not a promise")
    def make_promise(resolve, reject):
        def handle(v, is_rejected):
            try:
                engine = _ENGINE_HOLDER.get("engine")
                if onFinally and isinstance(onFinally, JSObj) and onFinally.kind == "function":
                    engine.call_js(onFinally, [], UNDEF)
            except Exception as e:
                reject(e)
                return
            if is_rejected:
                reject(v)
            else:
                resolve(v)
        
        def queue_handler(handler, value):
            engine = _ENGINE_HOLDER.get("engine")
            if engine:
                engine._queue_microtask(lambda: handler(value))
            else:
                handler(value)
        
        if state["status"] == "fulfilled":
            queue_handler(lambda v: handle(v, False), state["value"])
        elif state["status"] == "rejected":
            queue_handler(lambda v: handle(v, True), state["value"])
        else:
            state["handlers"].append({
                "onFulfilled": lambda v: queue_handler(lambda v: handle(v, False), v),
                "onRejected": lambda v: queue_handler(lambda v: handle(v, True), v)
            })
    return _promise_create(make_promise)


def _promise_create(executor):
    state = {"status": "pending", "value": None, "handlers": []}
    def resolve(v):
        if state["status"] != "pending":
            return
        # If v is a Promise, wait for it to settle
        if isinstance(v, JSObj) and v.kind == "promise":
            v.props["then"](resolve, reject)
            return
        state["status"] = "fulfilled"
        state["value"] = v
        for h in state["handlers"]:
            engine = _ENGINE_HOLDER.get("engine")
            if engine:
                engine._queue_microtask(lambda h=h, v=v: h["onFulfilled"](v))
            else:
                h["onFulfilled"](v)
        state["handlers"] = []
    def reject(v):
        if state["status"] != "pending":
            return
        state["status"] = "rejected"
        state["value"] = v
        for h in state["handlers"]:
            engine = _ENGINE_HOLDER.get("engine")
            if engine:
                engine._queue_microtask(lambda h=h, v=v: h["onRejected"](v))
            else:
                h["onRejected"](v)
        state["handlers"] = []
    try:
        executor(resolve, reject)
    except Exception as e:
        reject(e)
    p = JSObj(kind="promise")
    p.props["_state"] = state
    p.props["then"] = make_fn(lambda onF, onR=None: _promise_then(p, onF, onR), "then")
    p.props["catch"] = make_fn(lambda onR: _promise_then(p, None, onR), "catch")
    p.props["finally"] = make_fn(lambda onF: _promise_finally(p, onF), "finally")
    return p


def _promise_resolve(v):
    return _promise_create(lambda resolve, reject: resolve(v))


def _promise_reject(v):
    return _promise_create(lambda resolve, reject: reject(v))


def _promise_all(arr):
    if not isinstance(arr, JSObj) or arr.kind != "array":
        return _promise_reject("Promise.all requires an array")
    items = arr.arr
    if len(items) == 0:
        return _promise_resolve(make_array([]))
    return _promise_create(lambda resolve, reject: _promise_all_impl(items, resolve, reject))


def _promise_all_impl(items, resolve, reject):
    results = [None] * len(items)
    completed = 0
    def check_done():
        nonlocal completed
        completed += 1
        if completed == len(items):
            resolve(make_array(results))
    for i, item in enumerate(items):
        if isinstance(item, JSObj) and item.props.get("_state"):
            # It's a promise
            item.props["then"](
                lambda v, idx=i: (results.__setitem__(idx, v), check_done()),
                reject
            )
        else:
            results[i] = item
            check_done()


def _promise_race(arr):
    if not isinstance(arr, JSObj) or arr.kind != "array":
        return _promise_reject("Promise.race requires an array")
    items = arr.arr
    if len(items) == 0:
        return _promise_create(lambda resolve, reject: None)  # never settles
    return _promise_create(lambda resolve, reject: _promise_race_impl(items, resolve, reject))


def _promise_race_impl(items, resolve, reject):
    for item in items:
        if isinstance(item, JSObj) and item.props.get("_state"):
            item.props["then"](resolve, reject)
        else:
            resolve(item)


# ---------------------------------------------------------------------------
# node helpers bound at runtime
# ---------------------------------------------------------------------------
def _bind_engine(node, engine):
    node.js_engine = engine


def compile_handler(engine, node, attr_name, code):
    """Compile an inline onclick="..." handler lazily."""
    key = ("h", id(node), attr_name)
    fn = engine._handler_cache.get(key)
    if fn is None:
        if code == "→":
            return None
        try:
            ast = Parser("(function(e){ " + code + " })").parse()
            func_node = ast[1][0][1]  # the function expr node
            wrapped = JSObj(kind="function",
                            fn=JSFunc(func_node[1], func_node[2],
                                      engine.global_scope, False,
                                      "on" + attr_name[2:]),
                            name=attr_name)
            fn = wrapped
        except SyntaxError:
            fn = None
        engine._handler_cache[key] = fn
    return fn


# add slots the engine needs on Node objects