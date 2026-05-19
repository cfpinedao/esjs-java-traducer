# esjs-java-traducer

Traductor de **EsJS** a **Java** usando ANTLR4.

Pipeline:
```
codigo.esjs  ->  EsJsLexer  ->  EsJsParser  ->  parse tree  ->  JavaEmitter (visitor)  ->  Programa.java
```

La gramática es **idéntica** al traductor a Python — solo cambia el visitor.

## Requisitos

```bash
# Arch
sudo pacman -S antlr4 python-antlr4 jdk-openjdk

# pip alternativo (sin sudo)
pip install --user antlr4-tools antlr4-python3-runtime
```

Necesitas también `javac` y `java` para compilar y ejecutar la salida.

## Uso

```bash
# 1) Generar el parser (una sola vez)
./build.sh

# 2) Traducir un programa EsJS a Java
python3 traductor.py < ejemplos/hola.esjs > Programa.java

# 3) Compilar y ejecutar
javac Programa.java
java Programa
```

## Cómo se traduce la estructura

EsJS permite código en el "nivel superior". Java exige todo dentro de una clase con `main`. El traductor envuelve así:

```java
import java.util.*;
import java.util.function.*;

public class Programa {

    // funciones EsJS de nivel superior -> static methods
    static Object factorial(Object n) { ... }

    // clases EsJS de nivel superior -> static nested classes
    static class Animal { ... }

    public static void main(String[] args) {
        // resto del codigo de nivel superior
    }
}
```

## Mapeo principal EsJS → Java

| EsJS | Java |
|---|---|
| `consola.escribir(x)` | `System.out.println(x)` |
| `consola.error(x)` | `System.err.println(x)` |
| `consola.limpiar()` | `System.out.print("\033[2J\033[H")` (ANSI) |
| `Mate.raizCuadrada(x)` | `Math.sqrt(x)` |
| `Mate.absoluto(x)` | `Math.abs(x)` |
| `const x = 5` | `final var x = 5;` |
| `mut x = 5` / `var x = 5` | `var x = 5;` |
| `verdadero` / `falso` | `true` / `false` |
| `nulo` / `indefinido` | `null` |
| `Infinito` / `NuN` | `Double.POSITIVE_INFINITY` / `Double.NaN` |
| `si/sino` | `if/else` |
| `mientras` | `while` |
| `hacer ... mientras` | `do ... while` (nativo!) |
| `para (...)` | `for (...)` (nativo!) |
| `para (x de arr)` | `for (var x : arr)` |
| `elegir/caso/porDefecto` | `switch/case/default` (nativo!) |
| `intentar/capturar/finalmente` | `try/catch/finally` |
| `lanzar x` | `throw new RuntimeException(String.valueOf(x))` |
| `funcion f(a) { ... }` | `static Object f(Object a) { ... return null; }` |
| `clase X extiende Y` | `static class X extends Y` |
| `constructor(a) { ... }` | `public X(Object a) { ... }` |
| `crear C(a)` | `new C(a)` |
| `super(a)` | `super(a)` |
| `tipoDe x` | `x.getClass().getSimpleName()` |
| `instanciaDe` | `instanceof` |
| `&&` / `\|\|` / `!` | `&&` / `\|\|` / `!` |
| `==` / `===` | `==` (Java es estricto por tipo) |
| `**` | `Math.pow(a, b)` |
| `(x) => x*2` | `(x) -> x*2` |
| `[1,2,3]` | `List.of(1, 2, 3)` |
| `{a: 1}` | `Map.of("a", 1)` |
| `x.longitud` | `x.length` |

## Limitaciones conocidas

Java es estáticamente tipado; EsJS no. La traducción es **estructuralmente fiel** pero la salida no siempre compila tal cual:

- **Aritmética sobre `Object`**: `Object a = 5; Object b = 3; a + b;` no compila. Solo funciona cuando uno de los operandos es `String` (Java concatena por `toString()`).
- **Campos de clase**: el traductor escanea los métodos en busca de `this.X = ...` y declara `public Object X;`. Si asignás un campo desde fuera del constructor que no está declarado, hay que agregarlo manualmente.
- **Acceso a objetos literales**: `obj.nombre` se traduce literal pero `Map.of(...)` requiere `obj.get("nombre")`. Tradeoff documentado.
- **Funciones anónimas / `funcion` como expresión**: Java no tiene equivalente natural. Se emite comentario.
- **Flecha con cuerpo en bloque**: Java SI tiene `(x) -> { ... }`, pero traducir el cuerpo requiere captura de buffer — emite comentario por ahora.
- **`switch` sobre `Object`**: Java solo permite int/String/enum como discriminador clásico.
- **Comparación de igualdad sobre objetos**: usa `==` (referencia), no `equals`. Funciona para primitivos cacheados.
- **`tipoDe`**: devuelve nombre de clase Java, no el string JS (`"Integer"` en vez de `"number"`).

Para corregir esos casos automáticamente se necesitaría un runtime helper con métodos polimórficos — fuera del alcance de un traductor académico simple.
