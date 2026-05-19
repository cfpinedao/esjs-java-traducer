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

# Math.X — todos los metodos de Mate se mapean a Math.<nombre>
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


# ============================================================
# JavaEmitter
# ============================================================

class JavaEmitter(EsJsVisitor):
    """
    Emite codigo Java. Reparte la salida en dos buffers:
      - class_members: metodos static + clases anidadas estaticas (entre 'class Programa {' y main).
      - main_body:     sentencias de nivel superior, dentro de 'public static void main'.

    El flag self.in_main decide a cual buffer va cada emit().
    """

    CLASS_NAME = "Programa"

    def __init__(self):
        self.imports = set()
        self.class_members = []
        self.main_body = []
        self.indent = 0
        self.in_main = True
        self._current_class = None   # nombre de la clase EsJS que estamos emitiendo (para el ctor)

    # ---------- helpers de emision ----------
    def emit(self, line):
        target = self.main_body if self.in_main else self.class_members
        target.append("    " * self.indent + line)

    def _emit_block_body(self, stmts):
        """Visita una lista de sentencias; si esta vacia no emite nada (Java permite {})."""
        for s in stmts:
            self.visit(s)

    def _emit_sentence_body(self, sentencia_ctx):
        """Si la sentencia es un bloque, visita su contenido (ya estamos dentro de {); si no, visita la unica."""
        if isinstance(sentencia_ctx, EsJsParser.StmtBloqueContext):
            for s in sentencia_ctx.bloque().sentencia():
                self.visit(s)
        else:
            self.visit(sentencia_ctx)

    def output(self):
        out = []
        # imports
        default_imports = ["java.util.*", "java.util.function.*"]
        all_imports = set(default_imports) | self.imports
        for imp in sorted(all_imports):
            out.append(f"import {imp};")
        out.append("")
        out.append(f"public class {self.CLASS_NAME} {{")
        out.append("")
        # class members (static methods + nested classes)
        for line in self.class_members:
            out.append(("    " + line) if line.strip() else "")
        if self.class_members:
            out.append("")
        # main
        out.append("    public static void main(String[] args) {")
        for line in self.main_body:
            out.append(("        " + line) if line.strip() else "")
        out.append("    }")
        out.append("}")
        return "\n".join(out) + "\n"

    # ============================================================
    # ENTRY POINT
    # ============================================================

    def visitPrograma(self, ctx):
        # Separar declaraciones de funcion/clase (van a class_members) del resto (va a main).
        for s in ctx.sentencia():
            if isinstance(s, EsJsParser.StmtFunDeclContext) or isinstance(s, EsJsParser.StmtClassDeclContext):
                self.in_main = False
                self.indent = 0
                self.visit(s)
                self.emit("")  # linea en blanco entre miembros
            else:
                self.in_main = True
                self.indent = 0
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
        prefix = "final var " if kind == "const" else "var "
        for vi in decl.varInit():
            nombre = vi.ID().getText()
            if vi.expresion():
                valor = self.visit(vi.expresion())
                self.emit(f"{prefix}{nombre} = {valor};")
            else:
                # var requiere inicializador en Java; sin valor usamos Object.
                self.emit(f"Object {nombre} = null;")

    def visitStmtFunDecl(self, ctx):
        df = ctx.declFuncion()
        nombre = df.ID().getText()
        params = ", ".join(f"Object {p.getText()}" for p in df.parametros().ID())
        self.emit(f"static Object {nombre}({params}) {{")
        self.indent += 1
        self._emit_block_body(list(df.bloque().sentencia()))
        # default return — Java exige return en metodos no void
        self.emit("return null;")
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
        """Camina los metodos de la clase y extrae todos los nombres de campo asignados via this.X = ..."""
        fields = set()
        for m in class_ctx.metodo():
            self._walk_for_this_assign(m, fields)
        return fields

    def _walk_for_this_assign(self, node, fields):
        if isinstance(node, EsJsParser.ExprAssignContext):
            left = node.expresion(0)
            if isinstance(left, EsJsParser.ExprMemberContext) and isinstance(left.expresion(), EsJsParser.ExprThisContext):
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
        self._emit_block_body(list(ctx.bloque().sentencia()))
        self.emit("return null;")
        self.indent -= 1
        self.emit("}")

    def visitStmtIf(self, ctx):
        # Recoger toda la cadena si/sino-si/sino para emitir como if/else-if/else.
        branches = []   # [(cond_ctx, body_ctx)]
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
        # init
        init_str = ""
        if ctx.forInit():
            fi = ctx.forInit()
            if fi.declVariable():
                decl = fi.declVariable()
                kind = decl.start.text
                # for-init en Java: solo una declaracion (multiples vars requieren mismo tipo).
                # Usamos var con la primera; si hay multiples, sera invalido pero emitimos lo mejor posible.
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
        if isinstance(obj_ctx, EsJsParser.ExprConsolaContext):
            if name in CONSOLA_METODOS:
                return CONSOLA_METODOS[name]
            # consola.limpiar se maneja en visitExprCall
            if name == "limpiar":
                return "__consola_limpiar_marker"
        if isinstance(obj_ctx, EsJsParser.ExprMateContext):
            return f"Math.{MATE_METODOS.get(name, name)}"
        if name == "longitud":
            # Aproximacion: .length (funciona en arrays, no en List/String)
            return f"{self.visit(obj_ctx)}.length"
        return f"{self.visit(obj_ctx)}.{name}"

    def visitExprIndex(self, ctx):
        return f"{self.visit(ctx.expresion(0))}[{self.visit(ctx.expresion(1))}]"

    def visitExprCall(self, ctx):
        callee_ctx = ctx.expresion()
        args_node = ctx.argumentos()
        args_list = list(args_node.expresion()) if args_node else []
        args_str = ", ".join(self.visit(a) for a in args_list)

        # Caso especial: consola.limpiar() -> ANSI escape
        if isinstance(callee_ctx, EsJsParser.ExprMemberContext):
            inner = callee_ctx.expresion()
            if isinstance(inner, EsJsParser.ExprConsolaContext):
                if callee_ctx.memberName().getText() == "limpiar":
                    return 'System.out.print("\\u001b[2J\\u001b[H")'

        # Caso especial: super(args) -> super(args) (literal Java)
        if isinstance(callee_ctx, EsJsParser.ExprSuperContext):
            return f"super({args_str})"

        callee = self.visit(callee_ctx)
        return f"{callee}({args_str})"

    def visitExprPostfix(self, ctx):
        return f"{self.visit(ctx.expresion())}{ctx.op.text}"  # i++ / i--

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
        py_op = "==" if op in ("==", "===") else "!="
        return f"({self.visit(ctx.expresion(0))} {py_op} {self.visit(ctx.expresion(1))})"

    def visitExprAnd(self, ctx):
        return f"({self.visit(ctx.expresion(0))} && {self.visit(ctx.expresion(1))})"

    def visitExprOr(self, ctx):
        return f"({self.visit(ctx.expresion(0))} || {self.visit(ctx.expresion(1))})"

    def visitExprTernary(self, ctx):
        return f"({self.visit(ctx.expresion(0))} ? {self.visit(ctx.expresion(1))} : {self.visit(ctx.expresion(2))})"

    def visitExprAssign(self, ctx):
        target = self.visit(ctx.expresion(0))
        value = self.visit(ctx.expresion(1))
        return f"{target} {ctx.op.text} {value}"

    def visitExprArrow(self, ctx):
        params = [tok.getText() for tok in ctx.ID()]
        body_ctx = ctx.arrowBody()
        if body_ctx.bloque():
            return f"({', '.join(params)}) -> null /* cuerpo de flecha en bloque: traduccion no soportada */"
        body_str = self.visit(body_ctx.expresion())
        return f"({', '.join(params)}) -> {body_str}"

    def visitExprFunExpr(self, ctx):
        nombre = ctx.ID().getText() if ctx.ID() else "_anon"
        return f"null /* funcion expresion {nombre} no soportada en Java */"

    def visitExprParen(self, ctx):
        return f"({self.visit(ctx.expresion())})"

    def visitExprArray(self, ctx):
        elems = [self.visit(e) for e in ctx.expresion()]
        return f"List.of({', '.join(elems)})"

    def visitExprObject(self, ctx):
        items = [self.visit(p) for p in ctx.propiedad()]
        return f"Map.of({', '.join(items)})"

    def visitPropConValor(self, ctx):
        if ctx.ID():
            key = f'"{ctx.ID().getText()}"'
        elif ctx.STR():
            key = java_string(_strip_quotes(ctx.STR().getText()))
        else:
            key = ctx.NUM().getText()
        return f"{key}, {self.visit(ctx.expresion())}"

    def visitPropShorthand(self, ctx):
        name = ctx.ID().getText()
        return f'"{name}", {name}'

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
