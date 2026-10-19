"""Plataforma web de estimación de Pedidos Kids y Kits Escolares con Flask."""
import csv
from decimal import Decimal, ROUND_HALF_UP
import io
import json
import math
import os
from pathlib import Path
from flask import Flask, Response, abort, render_template, request, send_file

BASE = Path(__file__).resolve().parent
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024
MODELO = json.loads((BASE / "modelo.json").read_text(encoding="utf-8"))
COLUMNAS = MODELO["columnas"]
ETIQUETAS = {
    "consultas_web": "Consultas web de kits",
    "inversion_publicidad_soles": "Inversión en pauta digital (S/)",
    "campana_escolar": "Temporada Escolar / Alta Demanda"
}
EJEMPLOS = {
    "base": {"consultas_web": "25", "inversion_publicidad_soles": "300", "campana_escolar": "0"},
    "campana": {"consultas_web": "60", "inversion_publicidad_soles": "950", "campana_escolar": "1"},
}

def predecir(consultas, publicidad, campana):
    valores = dict(consultas_web=consultas, inversion_publicidad_soles=publicidad, campana_escolar=campana)
    return MODELO["intercepto"] + sum(MODELO["coeficientes"][c] * valores[c] for c in COLUMNAS)

def validar(formulario):
    valores, errores = {}, {}
    for campo in ("consultas_web", "inversion_publicidad_soles"):
        texto = str(formulario.get(campo, "")).strip()
        if not texto:
            errores[campo] = "Este campo es obligatorio."
            continue
        try:
            valor = float(texto)
            if not math.isfinite(valor):
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            errores[campo] = "Ingresa un valor numérico correcto."
            continue
        minimo, maximo = MODELO["rangos"][campo]
        if not minimo <= valor <= maximo:
            errores[campo] = f"El rango permitido es de {minimo} a {maximo}."
        elif campo == "consultas_web" and not valor.is_integer():
            errores[campo] = "Las consultas deben ser en números enteros."
        else:
            valores[campo] = valor
    campana = str(formulario.get("campana_escolar", ""))
    if campana not in ("0", "1"):
        errores["campana_escolar"] = "Selecciona una opción válida."
    else:
        valores["campana_escolar"] = int(campana)
    return valores, errores

def resultado_de(valores):
    valor = predecir(valores["consultas_web"], valores["inversion_publicidad_soles"], valores["campana_escolar"])
    pedidos = max(0, int(Decimal(str(valor)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
    entradas = {c: valores[c] for c in COLUMNAS}
    aportes = [{"nombre": ETIQUETAS[c], "valor": MODELO["coeficientes"][c] * valores[c]} for c in COLUMNAS]
    return {"valor": valor, "pedidos": pedidos, "consultas": int(valores["consultas_web"]),
            "publicidad": valores["inversion_publicidad_soles"],
            "campana": "Con temporada escolar activa" if valores["campana_escolar"] else "Sin temporada escolar",
            "entradas": entradas, "aportes": aportes}

def leer_csv(nombre):
    with (BASE / nombre).open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo))

@app.context_processor
def contexto():
    return {"modelo": MODELO}

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        return mostrar_simulador()
    ejemplos = {k: resultado_de(validar(v)[0]) for k, v in EJEMPLOS.items()}
    return render_template("index.html", activo="inicio", ejemplos=ejemplos)

def mostrar_simulador():
    ejemplo = request.args.get("ejemplo", "")
    campos = dict(EJEMPLOS.get(ejemplo, EJEMPLOS["base"]))
    resultado, errores = None, {}
    if request.method == "POST":
        campos = {c: request.form.get(c, "") for c in COLUMNAS}
        valores, errores = validar(campos)
        if not errores:
            resultado = resultado_de(valores)
    return render_template("simulador.html", activo="simulador", campos=campos,
                           errores=errores, resultado=resultado, ejemplo=ejemplo), (422 if errores else 200)

@app.route("/simulador", methods=["GET", "POST"])
def simulador():
    return mostrar_simulador()

def campos_comparacion(origen, usar_defectos=True):
    campos, valores, errores = {}, {}, {}
    for lado, defecto in (("a", "base"), ("b", "campana")):
        campos[lado] = {c: origen.get(f"{c}_{lado}", EJEMPLOS[defecto][c] if usar_defectos else "") for c in COLUMNAS}
        valores[lado], errores[lado] = validar(campos[lado])
    return campos, valores, errores

def resumen_comparacion(valores):
    a, b = resultado_de(valores["a"]), resultado_de(valores["b"])
    diferencia = b["valor"] - a["valor"]
    mayor = max(a["valor"], b["valor"], 1)
    return {"a": a, "b": b, "diferencia": diferencia,
            "presupuesto": b["publicidad"] - a["publicidad"],
            "barras": {"a": a["valor"] / mayor * 100, "b": b["valor"] / mayor * 100},
            "cambios": [{"nombre": ETIQUETAS[c], "entrada": valores["b"][c] - valores["a"][c],
                         "aporte": MODELO["coeficientes"][c] * (valores["b"][c] - valores["a"][c])} for c in COLUMNAS],
            "consulta": {f"{c}_{lado}": valores[lado][c] for lado in ("a", "b") for c in COLUMNAS}}

@app.route("/comparar", methods=["GET", "POST"])
def comparar():
    origen = request.form if request.method == "POST" else request.args
    campos, valores, errores = campos_comparacion(origen, usar_defectos=request.method == "GET")
    hay_errores = any(errores.values())
    resultado = None if hay_errores else resumen_comparacion(valores)
    return render_template("comparar.html", activo="comparar", campos=campos,
                           errores=errores, comparacion=resultado), (422 if hay_errores else 200)

def grafico_evaluacion():
    filas = sorted(leer_csv("predicciones_prueba.csv"), key=lambda r: r["semana"])
    puntos = []
    for i, fila in enumerate(filas):
        x = 45 + i * 590 / max(1, len(filas) - 1)
        real = float(fila["pedidos_kits"])
        pred = float(fila["prediccion_pedidos"])
        puntos.append({"x": x, "y": 217 - real / 45 * 180, "yp": 217 - pred / 45 * 180,
                       "semana": fila["semana"], "real": real, "pred": pred})
    return {"puntos": puntos, "linea": " ".join(f"{p['x']:.2f},{p['yp']:.2f}" for p in puntos)}

@app.get("/modelo")
def modelo():
    filas = leer_csv("datos.csv")
    filtro = request.args.get("campana", "")
    if filtro in ("0", "1"):
        filas = [fila for fila in filas if fila["campana_escolar"] == filtro]
    else:
        filtro = ""
    paginas = max(1, math.ceil(len(filas) / 10))
    try:
        pagina = max(1, min(int(request.args.get("pagina", "1")), paginas))
    except ValueError:
        pagina = 1
    return render_template("modelo.html", activo="modelo", grafico=grafico_evaluacion(),
                           filas=filas[(pagina - 1) * 10:pagina * 10], total=len(filas),
                           pagina=pagina, paginas=paginas, filtro=filtro, etiquetas=ETIQUETAS)

def respuesta_csv(nombre, encabezados, filas):
    salida = io.StringIO(newline="")
    writer = csv.writer(salida)
    writer.writerow(encabezados)
    writer.writerows(filas)
    return Response("\ufeff" + salida.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})

@app.get("/descargar")
def descargar():
    valores, errores = validar(request.args)
    if errores:
        abort(422, "Parámetros no válidos para la exportación.")
    resultado = resultado_de(valores)
    return respuesta_csv("reporte_kids_estimacion.csv", [*COLUMNAS, "pedidos_estimados", "pedidos_redondeados", "MAE", "R2", "simulado"],
                         [[*[valores[c] for c in COLUMNAS], resultado["valor"], resultado["pedidos"], MODELO["mae_prueba"], MODELO["r2_prueba"], "Sí"]])

@app.get("/datos.csv")
def descargar_datos():
    return send_file(BASE / "datos.csv", mimetype="text/csv", as_attachment=True, download_name="datos_historicos_kids.csv")

@app.get("/salud")
def salud():
    return {"estado": "ok", "sistema": "pedidos_kids_escolar"}

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5001")), debug=False)