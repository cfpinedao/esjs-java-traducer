#!/usr/bin/env python3
"""
Traductor EsJS -> Java (ANTLR4 + Visitor).

Pipeline:
    stdin -> EsJsLexer -> EsJsParser -> parse tree -> JavaEmitter.visit() -> Programa.java por stdout

Para regenerar el lexer/parser despues de modificar EsJs.g4:
    ./build.sh
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT / "generated"))

try:
    from antlr4 import InputStream, CommonTokenStream
    from EsJsLexer import EsJsLexer
    from EsJsParser import EsJsParser
    from EsJsVisitor import EsJsVisitor
except ImportError as e:
    sys.stderr.write(
        "Error: faltan dependencias.\n"
        "  1) pip install antlr4-python3-runtime    (o pacman -S python-antlr4)\n"
        "  2) ./build.sh\n"
        f"\nDetalle: {e}\n"
    )
    sys.exit(1)


# ============================================================
# Mapeos EsJS -> Java
# ============================================================

CONSOLA_METODOS = {
    "escribir": "System.out.println",
    "info":     "System.out.println",
    "error":    "System.err.println",
}

# Math.X — metodos basicos: lowercase -> Java Math method
MATE_METODOS = {
    "absoluto":     "abs",
    "raizCuadrada": "sqrt",
    "potencia":     "pow",
    "maximo":       "max",
    "minimo":       "min",
    "redondear":    "round",
    "aleatorio":    "random",
    "seno":         "sin",
    "coseno":       "cos",
    "tangente":     "tan",
    "logaritmo":    "log",
    "exponencial":  "exp",
}

# Mate.X constantes — Java no tiene LN2, LN10, etc. directos, los reemplazamos por expresiones equivalentes.
MATE_CONSTS_ESPECIAL = {
    "LN2":     "Math.log(2)",
    "LN10":    "Math.log(10)",
    "LOG2E":   "(1.0 / Math.log(2))",
    "LOG10E":  "(1.0 / Math.log(10))",
    "SQRT2":   "Math.sqrt(2)",
    "SQRT1_2": "Math.sqrt(0.5)",
}

# Numero.X — propiedades estaticas (sin parentesis) que se acceden via miembro.
# Funciones "globales" reservadas que se invocan sin prefijo (absoluto(-5) etc.)
FUNCIONES_GLOBALES = {
    "absoluto": "Math.abs",
}

NUMERO_PROPS = {
    "POSITIVE_INFINITY": "Double.POSITIVE_INFINITY",
    "NEGATIVE_INFINITY": "Double.NEGATIVE_INFINITY",
    "MAX_VALUE":         "Double.MAX_VALUE",
    "MIN_VALUE":         "Double.MIN_VALUE",
    "MAX_SAFE_INTEGER":  "9007199254740991L",
    "MIN_SAFE_INTEGER":  "-9007199254740991L",
    "EPSILON":           "2.220446049250313e-16",
    "NaN":               "Double.NaN",
}


def java_string(lex):
    """Re-envuelve un lexema de cadena en comillas dobles, escapando lo necesario."""
    out = []
    i = 0
    while i < len(lex):
        c = lex[i]
        if c == "\\" and i + 1 < len(lex):
            out.append(c + lex[i + 1]); i += 2; continue
        if c == '"':
            out.append('\\"')
        else:
            out.append(c)
        i += 1
    return f'"{"".join(out)}"'


def _strip_quotes(s):
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def _is_id_named(node, name):
    """True si node es un ExprIdContext cuyo identificador es `name`."""
    return isinstance(node, EsJsParser.ExprIdContext) and node.ID().getText() == name


# ============================================================
# JavaEmitter
# ============================================================

class JavaEmitter(EsJsVisitor):
    """
    Emite codigo Java. Reparte la salida en dos buffers:
      - class_members: metodos static + clases anidadas estaticas + campos hoisteados (entre 'class Programa {' y main).
      - main_body:     sentencias de nivel superior, dentro de 'public static void main'.
    """

    CLASS_NAME = "Programa"

    def __init__(self):
        self.imports = set()
        self.class_members = []
        self.main_body = []
        self.indent = 0
        self.in_main = True
        self._current_class = None
        self._hoisted_vars = set()    # 'var X' a nivel global, ya declarados como static fields
        self._local_hoisted = set()   # 'var X' dentro de la funcion/arrow actual
        self._needs_helpers = set()   # nombres de helpers a inyectar: _prop, _invoke, _len, _set

    # ---------- helpers de emision ----------
    def emit(self, line):
        target = self.main_body if self.in_main else self.class_members
        target.append("    " * self.indent + line)

    def _emit_block_body(self, stmts):
        for s in stmts:
            self.visit(s)

    def _emit_sentence_body(self, sentencia_ctx):
        if isinstance(sentencia_ctx, EsJsParser.StmtBloqueContext):
            for s in sentencia_ctx.bloque().sentencia():
                self.visit(s)
        else:
            self.visit(sentencia_ctx)

    def output(self):
        out = []
        default_imports = ["java.util.*", "java.util.function.*", "java.lang.reflect.*"]
        all_imports = set(default_imports) | self.imports
        for imp in sorted(all_imports):
            out.append(f"import {imp};")
        out.append("")
        out.append(f"public class {self.CLASS_NAME} {{")
        out.append("")
        # Inyectar helpers de runtime cuando se usen
        helpers = self._render_helpers()
        if helpers:
            out.extend("    " + l if l.strip() else "" for l in helpers)
            out.append("")
        for line in self.class_members:
            out.append(("    " + line) if line.strip() else "")
        if self.class_members:
            out.append("")
        out.append("    public static void main(String[] args) {")
        for line in self.main_body:
            out.append(("        " + line) if line.strip() else "")
        out.append("    }")
        out.append("}")
        return "\n".join(out) + "\n"

    def _render_helpers(self):
        lines = []
        if "_prop" in self._needs_helpers:
            lines += [
                "@SuppressWarnings({\"rawtypes\",\"unchecked\"})",
                "static Object _prop(Object o, String k) {",
                "    if (o == null) return null;",
                "    if (o instanceof Map) return ((Map)o).get(k);",
                "    try { return o.getClass().getField(k).get(o); }",
                "    catch (Exception e) { return null; }",
                "}",
            ]
        if "_invoke" in self._needs_helpers:
            lines += [
                "@SuppressWarnings({\"rawtypes\",\"unchecked\"})",
                "static Object _invoke(Object o, String k, Object... args) {",
                "    if (o == null) return null;",
                "    if (o instanceof Map) {",
                "        Object fn = ((Map)o).get(k);",
                "        if (fn instanceof Supplier) return ((Supplier)fn).get();",
                "        if (fn instanceof Function && args.length >= 1) return ((Function)fn).apply(args[0]);",
                "        if (fn instanceof BiFunction && args.length >= 2) return ((BiFunction)fn).apply(args[0], args[1]);",
                "        if (fn instanceof Runnable) { ((Runnable)fn).run(); return null; }",
                "        if (fn instanceof Consumer && args.length >= 1) { ((Consumer)fn).accept(args[0]); return null; }",
                "        if (fn instanceof BiConsumer && args.length >= 2) { ((BiConsumer)fn).accept(args[0], args[1]); return null; }",
                "        return null;",
                "    }",
                "    try {",
                "        Class<?>[] ts = new Class[args.length];",
                "        for (int i = 0; i < args.length; i++) ts[i] = Object.class;",
                "        return o.getClass().getMethod(k, ts).invoke(o, args);",
                "    } catch (Exception e) { return null; }",
                "}",
            ]
        if "_len" in self._needs_helpers:
            lines += [
                "static int _len(Object o) {",
                "    if (o instanceof CharSequence) return ((CharSequence)o).length();",
                "    if (o instanceof Collection) return ((Collection<?>)o).size();",
                "    if (o instanceof Map) return ((Map<?,?>)o).size();",
                "    if (o != null && o.getClass().isArray()) return Array.getLength(o);",
                "    return 0;",
                "}",
            ]
        if "_set" in self._needs_helpers:
            lines += [
                "@SuppressWarnings({\"rawtypes\",\"unchecked\"})",
                "static Object _set(Object o, String k, Object v) {",
                "    if (o instanceof Map) { ((Map)o).put(k, v); return v; }",
                "    try { o.getClass().getField(k).set(o, v); }",
                "    catch (Exception e) {}",
                "    return v;",
                "}",
            ]
        if "_index" in self._needs_helpers:
            lines += [
                "@SuppressWarnings({\"rawtypes\",\"unchecked\"})",
                "static Object _index(Object o, Object k) {",
                "    if (o instanceof Map) return ((Map)o).get(k);",
                "    if (o instanceof List) return ((List)o).get(((Number)k).intValue());",
                "    if (o != null && o.getClass().isArray()) return Array.get(o, ((Number)k).intValue());",
                "    return null;",
                "}",
            ]
        return lines

    # ============================================================
    # HOISTING HELPERS
    # ============================================================

    def _collect_var_hoists(self, stmts):
        """Recopila nombres de 'var X' en una lista de sentencias, sin cruzar funciones/clases/arrows."""
        names = []
        for s in stmts:
            self._walk_var_collect(s, names)
        return names

    def _walk_var_collect(self, node, names):
        if isinstance(node, (EsJsParser.StmtFunDeclContext,
                             EsJsParser.StmtClassDeclContext,
                             EsJsParser.MetodoCtorContext,
                             EsJsParser.MetodoNormalContext,
                             EsJsParser.ExprFunExprContext,
                             EsJsParser.ExprArrowContext)):
            return
        if isinstance(node, EsJsParser.StmtVarDeclContext):
            decl = node.declVariable()
            if decl.start.text == "var":
                for vi in decl.varInit():
                    names.append(vi.ID().getText())
        if hasattr(node, "children") and node.children:
            for child in node.children:
                self._walk_var_collect(child, names)

    def _last_is_return(self, stmts):
        return bool(stmts) and isinstance(stmts[-1], EsJsParser.StmtReturnContext)

    # ============================================================
    # ENTRY POINT — programa
    # ============================================================

    def visitPrograma(self, ctx):
        decl_stmts = []
        main_stmts = []
        for s in ctx.sentencia():
            if isinstance(s, (EsJsParser.StmtFunDeclContext, EsJsParser.StmtClassDeclContext)):
                decl_stmts.append(s)
            else:
                main_stmts.append(s)

        # Hoist 'var X' del scope global como static fields
        global_vars = self._collect_var_hoists(main_stmts)
        self._hoisted_vars = set(global_vars)

        self.in_main = False
        self.indent = 0
        for vn in sorted(set(global_vars)):
            self.emit(f"static Object {vn} = null;")
        if global_vars:
            self.emit("")

        # Emit function/class declarations
        for s in decl_stmts:
            self.in_main = False
            self.indent = 0
            self.visit(s)
            self.emit("")

        # Emit main body
        self.in_main = True
        self.indent = 0
        for s in main_stmts:
            self.visit(s)

    # ============================================================
    # SENTENCIAS
    # ============================================================

    def visitStmtBloque(self, ctx):
        stmts = list(ctx.bloque().sentencia())
        self.emit("{")
        self.indent += 1
        self._emit_block_body(stmts)
        self.indent -= 1
        self.emit("}")

    def visitStmtEmpty(self, ctx):
        pass

    def visitStmtVarDecl(self, ctx):
        decl = ctx.declVariable()
        kind = decl.start.text  # 'const' | 'mut' | 'var'

        for vi in decl.varInit():
            nombre = vi.ID().getText()
            valor_ctx = vi.expresion()

            # Caso especial: var/mut/const X = (params) => body  =>  emitir como static method
            if valor_ctx is not None and isinstance(valor_ctx, EsJsParser.ExprArrowContext):
                self._emit_arrow_as_method(nombre, valor_ctx)
                continue

            valor_str = self.visit(valor_ctx) if valor_ctx is not None else None

            if kind == "var":
                # Si esta hoisteada a nivel global, ya esta declarada como static field
                # Si esta hoisteada localmente, ya esta declarada al tope de la funcion
                # En cualquier caso emitimos solo la asignacion
                if valor_str is not None:
                    self.emit(f"{nombre} = {valor_str};")
                # sin valor: nada que emitir (queda en null hoisteado)
                continue

            # mut / const
            if valor_str is None:
                self.emit(f"Object {nombre} = null;")
            elif valor_str == "null":
                # var no infiere null; usamos Object
                if kind == "const":
                    self.emit(f"final Object {nombre} = null;")
                else:
                    self.emit(f"Object {nombre} = null;")
            else:
                prefix = "final var " if kind == "const" else "var "
                self.emit(f"{prefix}{nombre} = {valor_str};")

    def _emit_arrow_as_method(self, name, arrow_ctx):
        """Emite 'var X = (params) => body' como static method del Programa.
        Hace el truco que en Java permite invocar X(args) como cualquier funcion."""
        params = [tok.getText() for tok in arrow_ctx.ID()]
        params_str = ", ".join(f"Object {p}" for p in params)

        saved_in_main = self.in_main
        saved_indent = self.indent
        saved_local = self._local_hoisted
        self.in_main = False
        self.indent = 0

        self.emit(f"static Object {name}({params_str}) {{")
        self.indent += 1

        body = arrow_ctx.arrowBody()
        if body.bloque():
            block_stmts = list(body.bloque().sentencia())
            local_hoists = self._collect_var_hoists(block_stmts)
            self._local_hoisted = set(local_hoists)
            for vn in sorted(set(local_hoists)):
                self.emit(f"Object {vn} = null;")
            for s in block_stmts:
                self.visit(s)
            if not self._last_is_return(block_stmts):
                self.emit("return null;")
        else:
            ret = self.visit(body.expresion())
            self.emit(f"return {ret};")

        self.indent -= 1
        self.emit("}")
        self.emit("")

        self.in_main = saved_in_main
        self.indent = saved_indent
        self._local_hoisted = saved_local

    def visitStmtFunDecl(self, ctx):
        df = ctx.declFuncion()
        nombre = df.ID().getText()
        params = ", ".join(f"Object {p.getText()}" for p in df.parametros().ID())
        self.emit(f"static Object {nombre}({params}) {{")
        self.indent += 1

        block_stmts = list(df.bloque().sentencia())
        # Hoist 'var' locales dentro de la funcion
        saved_local = self._local_hoisted
        local_hoists = self._collect_var_hoists(block_stmts)
        self._local_hoisted = set(local_hoists)
        for vn in sorted(set(local_hoists)):
            self.emit(f"Object {vn} = null;")

        self._emit_block_body(block_stmts)

        if not self._last_is_return(block_stmts):
            self.emit("return null;")

        self._local_hoisted = saved_local
        self.indent -= 1
        self.emit("}")

    def visitStmtClassDecl(self, ctx):
        dc = ctx.declClase()
        ids = dc.ID()
        name = ids[0].getText()
        parent = ids[1].getText() if len(ids) > 1 else None

        fields = self._collect_fields(dc)
        ext = f" extends {parent}" if parent else ""
        self.emit(f"static class {name}{ext} {{")
        self.indent += 1
        for f in sorted(fields):
            self.emit(f"public Object {f};")
        if fields:
            self.emit("")
        prev = self._current_class
        self._current_class = name
        for m in dc.metodo():
            self.visit(m)
            self.emit("")
        self._current_class = prev
        self.indent -= 1
        self.emit("}")

    def _collect_fields(self, class_ctx):
        fields = set()
        for m in class_ctx.metodo():
            self._walk_for_this_assign(m, fields)
        return fields

    def _walk_for_this_assign(self, node, fields):
        if isinstance(node, EsJsParser.ExprAssignContext):
            left = node.expresion(0)
            if isinstance(left, EsJsParser.ExprMemberContext) and isinstance(left.expresion(),
                    (EsJsParser.ExprThisContext, EsJsParser.ExprAmbienteContext)):
                fields.add(left.memberName().getText())
        if hasattr(node, "children") and node.children:
            for child in node.children:
                self._walk_for_this_assign(child, fields)

    def visitMetodoCtor(self, ctx):
        params = ", ".join(f"Object {p.getText()}" for p in ctx.parametros().ID())
        self.emit(f"public {self._current_class}({params}) {{")
        self.indent += 1
        self._emit_block_body(list(ctx.bloque().sentencia()))
        self.indent -= 1
        self.emit("}")

    def visitMetodoNormal(self, ctx):
        nombre = ctx.ID().getText()
        params = ", ".join(f"Object {p.getText()}" for p in ctx.parametros().ID())
        self.emit(f"public Object {nombre}({params}) {{")
        self.indent += 1
        block_stmts = list(ctx.bloque().sentencia())
        self._emit_block_body(block_stmts)
        if not self._last_is_return(block_stmts):
            self.emit("return null;")
        self.indent -= 1
        self.emit("}")

    def visitStmtIf(self, ctx):
        branches = []
        else_branch = None
        current = ctx.sentenciaSi()
        while True:
            branches.append((current.expresion(), current.sentencia(0)))
            if current.SINO():
                else_sent = current.sentencia(1)
                if isinstance(else_sent, EsJsParser.StmtIfContext):
                    current = else_sent.sentenciaSi()
                    continue
                else:
                    else_branch = else_sent
                    break
            else:
                break

        for i, (cond_ctx, body_ctx) in enumerate(branches):
            cond_str = self.visit(cond_ctx)
            if i == 0:
                self.emit(f"if ({cond_str}) {{")
            else:
                self.emit(f"}} else if ({cond_str}) {{")
            self.indent += 1
            self._emit_sentence_body(body_ctx)
            self.indent -= 1

        if else_branch is not None:
            self.emit("} else {")
            self.indent += 1
            self._emit_sentence_body(else_branch)
            self.indent -= 1
            self.emit("}")
        else:
            self.emit("}")

    def visitStmtWhile(self, ctx):
        sm = ctx.sentenciaMientras()
        cond = self.visit(sm.expresion())
        self.emit(f"while ({cond}) {{")
        self.indent += 1
        self._emit_sentence_body(sm.sentencia())
        self.indent -= 1
        self.emit("}")

    def visitStmtDoWhile(self, ctx):
        sh = ctx.sentenciaHacer()
        self.emit("do {")
        self.indent += 1
        self._emit_sentence_body(sh.sentencia())
        self.indent -= 1
        cond = self.visit(sh.expresion())
        self.emit(f"}} while ({cond});")

    def visitStmtFor(self, ctx):
        self.visit(ctx.sentenciaPara())

    def visitParaEnDe(self, ctx):
        var = ctx.ID().getText()
        it = self.visit(ctx.expresion())
        self.emit(f"for (var {var} : {it}) {{")
        self.indent += 1
        self._emit_sentence_body(ctx.sentencia())
        self.indent -= 1
        self.emit("}")

    def visitParaC(self, ctx):
        init_str = ""
        if ctx.forInit():
            fi = ctx.forInit()
            if fi.declVariable():
                decl = fi.declVariable()
                kind = decl.start.text
                inits = []
                for vi in decl.varInit():
                    v = self.visit(vi.expresion()) if vi.expresion() else "null"
                    inits.append(f"{vi.ID().getText()} = {v}")
                if len(inits) == 1:
                    prefix = "final var " if kind == "const" else "var "
                    init_str = prefix + inits[0]
                else:
                    init_str = "var " + ", ".join(inits)
            elif fi.expresion():
                init_str = self.visit(fi.expresion())
        cond_str = self.visit(ctx.forCond().expresion()) if ctx.forCond() else ""
        incr_str = self.visit(ctx.forIncr().expresion()) if ctx.forIncr() else ""
        self.emit(f"for ({init_str}; {cond_str}; {incr_str}) {{")
        self.indent += 1
        self._emit_sentence_body(ctx.sentencia())
        self.indent -= 1
        self.emit("}")

    def visitStmtSwitch(self, ctx):
        se = ctx.sentenciaElegir()
        disc = self.visit(se.expresion())
        self.emit(f"switch ({disc}) {{")
        self.indent += 1
        for cl in se.clausula():
            if isinstance(cl, EsJsParser.ClausulaCasoContext):
                val = self.visit(cl.expresion())
                self.emit(f"case {val}:")
            else:
                self.emit("default:")
            self.indent += 1
            for s in cl.sentencia():
                self.visit(s)
            self.indent -= 1
        self.indent -= 1
        self.emit("}")

    def visitStmtTry(self, ctx):
        si_ctx = ctx.sentenciaIntentar()
        bloques = list(si_ctx.bloque())
        try_body = bloques[0]
        catch_body = bloques[1]
        finally_body = bloques[2] if len(bloques) > 2 else None
        catch_id = si_ctx.ID().getText() if si_ctx.ID() else "_e"
        self.emit("try {")
        self.indent += 1
        self._emit_block_body(list(try_body.sentencia()))
        self.indent -= 1
        self.emit(f"}} catch (Exception {catch_id}) {{")
        self.indent += 1
        self._emit_block_body(list(catch_body.sentencia()))
        self.indent -= 1
        if finally_body is not None:
            self.emit("} finally {")
            self.indent += 1
            self._emit_block_body(list(finally_body.sentencia()))
            self.indent -= 1
        self.emit("}")

    def visitStmtBreak(self, ctx):    self.emit("break;")
    def visitStmtContinue(self, ctx): self.emit("continue;")

    def visitStmtReturn(self, ctx):
        if ctx.expresion():
            self.emit(f"return {self.visit(ctx.expresion())};")
        else:
            self.emit("return null;")

    def visitStmtThrow(self, ctx):
        self.emit(f"throw new RuntimeException(String.valueOf({self.visit(ctx.expresion())}));")

    def visitStmtExpr(self, ctx):
        self.emit(f"{self.visit(ctx.expresion())};")

    # ============================================================
    # EXPRESIONES (retornan str con Java equivalente)
    # ============================================================

    def visitExprMember(self, ctx):
        obj_ctx = ctx.expresion()
        name = ctx.memberName().getText()

        # consola.X
        if isinstance(obj_ctx, EsJsParser.ExprConsolaContext):
            if name in CONSOLA_METODOS:
                return CONSOLA_METODOS[name]
            if name == "limpiar":
                return "__consola_limpiar_marker"

        # Mate.X
        if isinstance(obj_ctx, EsJsParser.ExprMateContext):
            if name in MATE_CONSTS_ESPECIAL:
                return MATE_CONSTS_ESPECIAL[name]
            return f"Math.{MATE_METODOS.get(name, name)}"

        # Numero.X
        if _is_id_named(obj_ctx, "Numero"):
            if name in NUMERO_PROPS:
                return NUMERO_PROPS[name]
            return f"__Numero_{name}"

        # this.X / ambiente.X — acceso directo (campo declarado en la clase)
        if isinstance(obj_ctx, (EsJsParser.ExprThisContext, EsJsParser.ExprAmbienteContext)):
            return f"this.{name}"

        # x.longitud — usar helper que cubre String/Collection/Map/array
        if name == "longitud":
            self._needs_helpers.add("_len")
            return f"_len({self.visit(obj_ctx)})"

        # Resto: acceso dinamico via reflexion/Map.get
        self._needs_helpers.add("_prop")
        return f'_prop({self.visit(obj_ctx)}, "{name}")'

    def visitExprIndex(self, ctx):
        # En EsJS obj[k] puede ser array (k=int), Map (k=string), o List (k=int).
        # Usamos helper para no comprometernos al tipo en compile-time.
        self._needs_helpers.add("_index")
        return f"_index({self.visit(ctx.expresion(0))}, {self.visit(ctx.expresion(1))})"

    def visitExprCall(self, ctx):
        callee_ctx = ctx.expresion()
        args_node = ctx.argumentos()
        args_list = list(args_node.expresion()) if args_node else []
        args_strs = [self.visit(a) for a in args_list]
        args_str = ", ".join(args_strs)

        # Funciones globales reservadas (absoluto(x) -> Math.abs(x))
        if isinstance(callee_ctx, EsJsParser.ExprIdContext):
            fname = callee_ctx.ID().getText()
            if fname in FUNCIONES_GLOBALES:
                return f"{FUNCIONES_GLOBALES[fname]}({args_str})"

        # super(args) -> super(args)
        if isinstance(callee_ctx, EsJsParser.ExprSuperContext):
            return f"super({args_str})"

        # Casos especiales sobre miembros
        if isinstance(callee_ctx, EsJsParser.ExprMemberContext):
            inner_ctx = callee_ctx.expresion()
            method_name = callee_ctx.memberName().getText()

            # consola.escribir/info/error(...) — manejar multiples argumentos
            if isinstance(inner_ctx, EsJsParser.ExprConsolaContext) and method_name in CONSOLA_METODOS:
                target = CONSOLA_METODOS[method_name]
                if len(args_strs) == 0:
                    return f"{target}()"
                if len(args_strs) == 1:
                    return f"{target}({args_strs[0]})"
                # multi-arg: concatenar separados por espacio (como JS console.log)
                concat = ' + " " + '.join(f"String.valueOf({a})" for a in args_strs)
                return f"{target}({concat})"

            # consola.limpiar()
            if isinstance(inner_ctx, EsJsParser.ExprConsolaContext) and method_name == "limpiar":
                return 'System.out.print("\\u001b[2J\\u001b[H")'

            # Numero.X(args)
            if _is_id_named(inner_ctx, "Numero"):
                first = args_str
                if method_name == "interpretarDecimal":
                    return f"Double.parseDouble(String.valueOf({first}))"
                if method_name == "interpretarEntero":
                    return f"Integer.parseInt(String.valueOf({first}))"
                if method_name == "esFinito":
                    return f"Double.isFinite(((Number)({first})).doubleValue())"
                if method_name == "esEntero":
                    return f"(((Number)({first})).doubleValue() == Math.floor(((Number)({first})).doubleValue()))"
                if method_name == "esEnteroSeguro":
                    return (f"(((Number)({first})).doubleValue() == Math.floor(((Number)({first})).doubleValue())"
                            f" && Math.abs(((Number)({first})).doubleValue()) <= 9007199254740991.0)")
                if method_name == "esNuN":
                    return f"Double.isNaN(((Number)({first})).doubleValue())"

            # Metodos de instancia tipo-Numero sobre cualquier expresion
            inner_str = self.visit(inner_ctx)
            if method_name == "aCadena":
                return f"String.valueOf({inner_str})"
            if method_name == "fijarDecimales":
                return (f'String.format(Locale.US, "%." + ({args_str}) + "f", '
                        f'((Number)({inner_str})).doubleValue())')
            if method_name == "valorDe":
                return inner_str
            if method_name == "aExponencial":
                return f'String.format(Locale.US, "%e", ((Number)({inner_str})).doubleValue())'

            # Si llegamos aca, es una llamada metodo sobre un objeto dinamico.
            # Mate ya retorno "Math.x" (statico, callable directo). this/ambiente tambien.
            # Para los demas (incluidas instancias de clase), usar reflexion para evitar errores de compilacion.
            if isinstance(inner_ctx, (EsJsParser.ExprThisContext, EsJsParser.ExprAmbienteContext,
                                       EsJsParser.ExprMateContext, EsJsParser.ExprConsolaContext)):
                callee = self.visit(callee_ctx)
                return f"{callee}({args_str})"
            # Reflexion
            self._needs_helpers.add("_invoke")
            extra = f", {args_str}" if args_str else ""
            return f'_invoke({inner_str}, "{method_name}"{extra})'

        callee = self.visit(callee_ctx)
        return f"{callee}({args_str})"

    def visitExprPostfix(self, ctx):
        return f"{self.visit(ctx.expresion())}{ctx.op.text}"

    def visitExprUnary(self, ctx):
        op = ctx.op.text
        operand = self.visit(ctx.expresion())
        if op == "!":
            return f"(!{operand})"
        return f"({op}{operand})"

    def visitExprTypeOf(self, ctx):
        return f"{self.visit(ctx.expresion())}.getClass().getSimpleName()"

    def visitExprDelete(self, ctx):
        return f"/* eliminar {self.visit(ctx.expresion())} no soportado en Java */ null"

    def visitExprNew(self, ctx):
        sub_ctx = ctx.expresion()
        sub_str = self.visit(sub_ctx)
        if isinstance(sub_ctx, EsJsParser.ExprCallContext):
            return f"new {sub_str}"
        return f"new {sub_str}()"

    def visitExprPow(self, ctx):
        l = self.visit(ctx.expresion(0))
        r = self.visit(ctx.expresion(1))
        return f"Math.pow({l}, {r})"

    def visitExprMul(self, ctx):
        return f"({self.visit(ctx.expresion(0))} {ctx.op.text} {self.visit(ctx.expresion(1))})"

    def visitExprAdd(self, ctx):
        return f"({self.visit(ctx.expresion(0))} {ctx.op.text} {self.visit(ctx.expresion(1))})"

    def visitExprComp(self, ctx):
        return f"({self.visit(ctx.expresion(0))} {ctx.op.text} {self.visit(ctx.expresion(1))})"

    def visitExprInstanceOf(self, ctx):
        return f"({self.visit(ctx.expresion(0))} instanceof {self.visit(ctx.expresion(1))})"

    def visitExprEq(self, ctx):
        op = ctx.op.text
        left = self.visit(ctx.expresion(0))
        right = self.visit(ctx.expresion(1))
        if op in ("==", "==="):
            return f"Objects.equals({left}, {right})"
        return f"(!Objects.equals({left}, {right}))"

    def visitExprAnd(self, ctx):
        return f"({self.visit(ctx.expresion(0))} && {self.visit(ctx.expresion(1))})"

    def visitExprOr(self, ctx):
        return f"({self.visit(ctx.expresion(0))} || {self.visit(ctx.expresion(1))})"

    def visitExprTernary(self, ctx):
        return f"({self.visit(ctx.expresion(0))} ? {self.visit(ctx.expresion(1))} : {self.visit(ctx.expresion(2))})"

    def visitExprAssign(self, ctx):
        left_ctx = ctx.expresion(0)
        value_str = self.visit(ctx.expresion(1))
        op = ctx.op.text

        # Caso especial: obj.X = value sobre objeto dinamico (no this/super/Mate/consola)
        # No podemos hacer "_prop(obj, X) = value", usamos _set.
        if op == "=" and isinstance(left_ctx, EsJsParser.ExprMemberContext):
            inner_ctx = left_ctx.expresion()
            if not isinstance(inner_ctx, (EsJsParser.ExprThisContext, EsJsParser.ExprAmbienteContext,
                                           EsJsParser.ExprMateContext, EsJsParser.ExprConsolaContext)):
                self._needs_helpers.add("_set")
                obj_str = self.visit(inner_ctx)
                name = left_ctx.memberName().getText()
                return f'_set({obj_str}, "{name}", {value_str})'

        target = self.visit(left_ctx)
        return f"{target} {op} {value_str}"

    def visitExprArrow(self, ctx):
        # Caso "suelto" (no asignado a una variable): lambda real
        params = [tok.getText() for tok in ctx.ID()]
        body_ctx = ctx.arrowBody()
        if body_ctx.bloque():
            return f"({', '.join(params)}) -> null /* cuerpo de flecha en bloque: usar mut/var/const X = (params) => {{ ... }} para traducir como metodo */"
        body_str = self.visit(body_ctx.expresion())
        return f"({', '.join(params)}) -> {body_str}"

    def visitExprFunExpr(self, ctx):
        nombre = ctx.ID().getText() if ctx.ID() else "_anon"
        return f"null /* funcion expresion {nombre} no traducible directamente */"

    def visitExprParen(self, ctx):
        return f"({self.visit(ctx.expresion())})"

    def visitExprArray(self, ctx):
        elems = [self.visit(e) for e in ctx.expresion()]
        # ArrayList mutable (List.of() es inmutable y rompe agregar)
        if not elems:
            return "new ArrayList<>()"
        return f"new ArrayList<>(List.of({', '.join(elems)}))"

    def visitExprObject(self, ctx):
        # HashMap mutable para soportar agregados dinamicos
        items = [self.visit(p) for p in ctx.propiedad()]
        # Filtrar items vacios (de PropMetodo que skipea)
        items = [it for it in items if it]
        if not items:
            return "new HashMap<>()"
        return f"new HashMap<>(Map.ofEntries({', '.join(items)}))"

    def visitPropConValor(self, ctx):
        if ctx.ID():
            key = f'"{ctx.ID().getText()}"'
        elif ctx.STR():
            key = java_string(_strip_quotes(ctx.STR().getText()))
        else:
            key = ctx.NUM().getText()
        return f"Map.entry({key}, {self.visit(ctx.expresion())})"

    def visitPropShorthand(self, ctx):
        name = ctx.ID().getText()
        return f'Map.entry("{name}", {name})'

    def visitPropMetodo(self, ctx):
        # Java no permite metodos dentro de Map literal. Lo omitimos con un comentario; el objeto resultante NO tendra ese metodo.
        return ""

    # ----- literales y nombres -----
    def visitExprNum(self, ctx):    return ctx.NUM().getText()
    def visitExprStr(self, ctx):    return java_string(_strip_quotes(ctx.STR().getText()))
    def visitExprTrue(self, ctx):   return "true"
    def visitExprFalse(self, ctx):  return "false"
    def visitExprNull(self, ctx):   return "null"
    def visitExprUndef(self, ctx):  return "null"
    def visitExprInf(self, ctx):    return "Double.POSITIVE_INFINITY"
    def visitExprNaN(self, ctx):    return "Double.NaN"
    def visitExprThis(self, ctx):   return "this"
    def visitExprSuper(self, ctx):  return "super"
    def visitExprAmbiente(self, ctx): return "this"     # ambiente en EsJS == this de JS
    def visitExprConsola(self, ctx):return "System.out"
    def visitExprMate(self, ctx):   return "Math"
    def visitExprId(self, ctx):     return ctx.ID().getText()


# ============================================================
# MAIN
# ============================================================

def traducir(codigo: str) -> str:
    stream = InputStream(codigo)
    lexer = EsJsLexer(stream)
    tokens = CommonTokenStream(lexer)
    parser = EsJsParser(tokens)
    tree = parser.programa()
    emitter = JavaEmitter()
    emitter.visit(tree)
    return emitter.output()


def main():
    sys.stdout.write(traducir(sys.stdin.read()))


if __name__ == "__main__":
    main()
