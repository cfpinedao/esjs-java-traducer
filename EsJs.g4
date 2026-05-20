grammar EsJs;

// ============================================================
// PARSER RULES (minuscula inicial)
// ============================================================

programa : sentencia* EOF ;

// ----- sentencias -----

sentencia
    : bloque                                                                #StmtBloque
    | declVariable SEMI?                                                    #StmtVarDecl
    | declFuncion                                                           #StmtFunDecl
    | declClase                                                             #StmtClassDecl
    | sentenciaSi                                                           #StmtIf
    | sentenciaMientras                                                     #StmtWhile
    | sentenciaHacer SEMI?                                                  #StmtDoWhile
    | sentenciaPara                                                         #StmtFor
    | sentenciaElegir                                                       #StmtSwitch
    | sentenciaIntentar                                                     #StmtTry
    | ROMPER SEMI?                                                          #StmtBreak
    | CONTINUAR SEMI?                                                       #StmtContinue
    | RETORNAR expresion? SEMI?                                             #StmtReturn
    | LANZAR expresion SEMI?                                                #StmtThrow
    | expresion SEMI?                                                       #StmtExpr
    | SEMI                                                                  #StmtEmpty
    ;

bloque : LBRACE sentencia* RBRACE ;

declVariable : (CONST | MUT | VAR) varInit (COMMA varInit)* ;
varInit      : ID (ASSIGN expresion)? ;

declFuncion  : FUNCION ID parametros bloque ;
parametros   : LPAR (ID (COMMA ID)*)? RPAR ;

declClase    : CLASE ID (EXTIENDE ID)? LBRACE metodo* RBRACE ;
metodo
    : CONSTRUCTOR parametros bloque                                         #MetodoCtor
    | FUNCION? ID parametros bloque                                         #MetodoNormal
    ;

sentenciaSi
    : SI LPAR expresion RPAR sentencia (SINO sentencia)?
    ;

sentenciaMientras
    : MIENTRAS LPAR expresion RPAR sentencia
    ;

sentenciaHacer
    : HACER sentencia MIENTRAS LPAR expresion RPAR
    ;

sentenciaPara
    // for x en/de iter — listado primero por ser mas especifico
    : PARA LPAR (CONST | MUT | VAR)? ID (EN | DE) expresion RPAR sentencia  #ParaEnDe
    | PARA LPAR forInit? SEMI forCond? SEMI forIncr? RPAR sentencia         #ParaC
    ;
forInit : declVariable | expresion ;
forCond : expresion ;
forIncr : expresion ;

sentenciaElegir
    : ELEGIR LPAR expresion RPAR LBRACE clausula* RBRACE
    ;
clausula
    : CASO expresion COLON sentencia*                                       #ClausulaCaso
    | POR_DEF COLON sentencia*                                              #ClausulaDefecto
    ;

sentenciaIntentar
    : INTENTAR bloque CAPTURAR (LPAR ID? RPAR)? bloque (FINALMENT bloque)?
    ;

// ----- expresiones (precedencia por orden: las alternativas listadas
//       PRIMERO tienen MAYOR precedencia / atan mas fuerte) ----

expresion
    // ----- postfijo (mayor precedencia) -----
    : expresion DOT memberName                                              #ExprMember
    | expresion LBRACK expresion RBRACK                                     #ExprIndex
    | expresion LPAR argumentos? RPAR                                       #ExprCall
    | expresion op=(INC | DEC)                                              #ExprPostfix

    // ----- unario -----
    | op=(NOT_ | MINUS | PLUS | INC | DEC) expresion                        #ExprUnary
    | TIPO_DE expresion                                                     #ExprTypeOf
    | ELIMINAR expresion                                                    #ExprDelete
    | CREAR expresion                                                       #ExprNew

    // ----- potencia (asociatividad por derecha) -----
    | <assoc=right> expresion POW expresion                                 #ExprPow

    // ----- multiplicativo -----
    | expresion op=(TIMES | DIV | MOD) expresion                            #ExprMul

    // ----- aditivo -----
    | expresion op=(PLUS | MINUS) expresion                                 #ExprAdd

    // ----- comparacion -----
    | expresion op=(LT | LEQ | GT | GEQ) expresion                          #ExprComp
    | expresion INSTANCIA_DE expresion                                      #ExprInstanceOf

    // ----- igualdad -----
    | expresion op=(STRICT_EQ | STRICT_NEQ | EQ | NEQ) expresion            #ExprEq

    // ----- logico AND -----
    | expresion AND_ expresion                                              #ExprAnd

    // ----- logico OR -----
    | expresion OR_ expresion                                               #ExprOr

    // ----- ternario (right-assoc) -----
    | <assoc=right> expresion QUESTION expresion COLON expresion            #ExprTernary

    // ----- asignacion (right-assoc, MENOR precedencia entre operadores) -----
    | <assoc=right> expresion op=(ASSIGN | PLUS_ASSIGN | MINUS_ASSIGN
                                | TIMES_ASSIGN | DIV_ASSIGN | MOD_ASSIGN
                                | POW_ASSIGN) expresion                     #ExprAssign

    // ----- primarios (hojas) -----
    // Flecha listada antes que ExprParen porque comparten prefijo '('
    | LPAR (ID (COMMA ID)*)? RPAR ARROW arrowBody                           #ExprArrow
    | FUNCION ID? parametros bloque                                         #ExprFunExpr
    | LPAR expresion RPAR                                                   #ExprParen
    | LBRACK (expresion (COMMA expresion)*)? RBRACK                         #ExprArray
    | LBRACE (propiedad (COMMA propiedad)*)? RBRACE                         #ExprObject
    | NUM                                                                   #ExprNum
    | STR                                                                   #ExprStr
    | VERDADERO                                                             #ExprTrue
    | FALSO                                                                 #ExprFalse
    | NULO                                                                  #ExprNull
    | INDEFINIDO                                                            #ExprUndef
    | INFINITO                                                              #ExprInf
    | NAN_                                                                  #ExprNaN
    | THIS                                                                  #ExprThis
    | SUPER                                                                 #ExprSuper
    | AMBIENTE                                                              #ExprAmbiente
    | CONSOLA                                                               #ExprConsola
    | MATE                                                                  #ExprMate
    | ID                                                                    #ExprId
    ;

arrowBody  : bloque | expresion ;
argumentos : expresion (COMMA expresion)* ;

// Nombre de miembro tras un '.' — admite ID o cualquier palabra reservada
// (porque JS/EsJS permite reservadas como nombres de propiedad).
memberName
    : ID | SI | SINO | ELEGIR | CASO | POR_DEF | PARA | MIENTRAS | HACER
    | ROMPER | CONTINUAR | RETORNAR | INTENTAR | CAPTURAR | FINALMENT
    | LANZAR | CONST | MUT | VAR | EN | DE | FUNCION | CLASE | EXTIENDE
    | CONSTRUCTOR | SUPER | CREAR | ELIMINAR | TIPO_DE | INSTANCIA_DE
    | VERDADERO | FALSO | NULO | INDEFINIDO | INFINITO | NAN_
    | THIS | AMBIENTE | CONSOLA | MATE
    ;

propiedad
    : (ID | STR | NUM) COLON expresion                                      #PropConValor
    | ID parametros bloque                                                  #PropMetodo
    | ID                                                                    #PropShorthand
    ;

// ============================================================
// LEXER RULES (mayuscula inicial)
// ============================================================

// Palabras reservadas — DEBEN ir antes que ID
SI           : 'si' ;
SINO         : 'sino' ;
ELEGIR       : 'elegir' ;
CASO         : 'caso' ;
POR_DEF      : 'porDefecto' ;
PARA         : 'para' ;
MIENTRAS     : 'mientras' ;
HACER        : 'hacer' ;
ROMPER       : 'romper' ;
CONTINUAR    : 'continuar' ;
RETORNAR     : 'retornar' ;
INTENTAR     : 'intentar' ;
CAPTURAR     : 'capturar' ;
FINALMENT    : 'finalmente' ;
LANZAR       : 'lanzar' ;
CONST        : 'const' ;
MUT          : 'mut' ;
VAR          : 'var' ;
EN           : 'en' ;
DE           : 'de' ;
FUNCION      : 'funcion' ;
CLASE        : 'clase' ;
EXTIENDE     : 'extiende' ;
CONSTRUCTOR  : 'constructor' ;
SUPER        : 'super' ;
CREAR        : 'crear' ;
ELIMINAR     : 'eliminar' ;
TIPO_DE      : 'tipoDe' ;
INSTANCIA_DE : 'instanciaDe' ;
VERDADERO    : 'verdadero' ;
FALSO        : 'falso' ;
NULO         : 'nulo' ;
INDEFINIDO   : 'indefinido' ;
INFINITO     : 'Infinito' ;
NAN_         : 'NuN' ;
THIS         : 'this' ;
AMBIENTE     : 'ambiente' ;
CONSOLA      : 'consola' ;
MATE         : 'Mate' ;

// Operadores compuestos primero (longest match)
POW_ASSIGN   : '**=' ;
STRICT_EQ    : '===' ;
STRICT_NEQ   : '!==' ;
SPREAD       : '...' ;
NULLISH      : '??' ;
POW          : '**' ;
INC          : '++' ;
DEC          : '--' ;
ARROW        : '=>' ;
PLUS_ASSIGN  : '+=' ;
MINUS_ASSIGN : '-=' ;
TIMES_ASSIGN : '*=' ;
DIV_ASSIGN   : '/=' ;
MOD_ASSIGN   : '%=' ;
EQ           : '==' ;
NEQ          : '!=' ;
LEQ          : '<=' ;
GEQ          : '>=' ;
AND_         : '&&' ;
OR_          : '||' ;
ASSIGN       : '=' ;
PLUS         : '+' ;
MINUS        : '-' ;
TIMES        : '*' ;
DIV          : '/' ;
MOD          : '%' ;
LT           : '<' ;
GT           : '>' ;
NOT_         : '!' ;
DOT          : '.' ;
LPAR         : '(' ;
RPAR         : ')' ;
LBRACE       : '{' ;
RBRACE       : '}' ;
LBRACK       : '[' ;
RBRACK       : ']' ;
COMMA        : ',' ;
SEMI         : ';' ;
COLON        : ':' ;
QUESTION     : '?' ;

// Literales
NUM : [0-9]+ ('.' [0-9]+)? ;

STR : '"'  (~["\\\r\n]  | '\\' .)* '"'
    | '\'' (~['\\\r\n]  | '\\' .)* '\''
    ;

// Identificador (ASCII + Latin extended para acentos)
ID  : [a-zA-Z_$À-ɏ] [a-zA-Z0-9_$À-ɏ]* ;

// Skips
LINE_COMMENT  : '//' ~[\r\n]*   -> skip ;
BLOCK_COMMENT : '/*' .*? '*/'   -> skip ;
WS            : [ \t\r\n]+      -> skip ;
