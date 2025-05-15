# Archivo: app.py corregido y optimizado

import streamlit as st
import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import plotly.express as px
import plotly.graph_objects as go
import io
import uuid

#Def de Funcion Simple para VPN
def calcular_vpn_simple(flujo_anual, tasa):
    return sum([
        flujo_anual[i] / ((1 + tasa) ** (i + 1))
        for i in range(len(flujo_anual))
    ])

#Def de Funcion para VPN
def calcular_vpn_solucion(
    sol,
    tasa_descuento,
    n_anios_default,
    gastos_adicionales_comunes,
    precio_carbono,
    multiplicador_precio_carbono,
    crecimiento_precio_carbono,
    crecimiento_ingreso_encadenado
):
    dur = int(sol["Duración (años)"])
    area_total = sol["Área (ha)"] * multiplicador_area
    tipo_captura = sol.get("Tipo Captura", "constante")
    tipo_sn = sol.get("Tipo SNC", "restauracion")
    anos_area_escalonada = sol.get("Años Escalonamiento", 1)

    if anos_area_escalonada == 1:
        area_por_anio = np.full(dur, area_total)
    else:
        area_por_anio = np.concatenate([
            np.linspace(area_total / anos_area_escalonada, area_total, anos_area_escalonada),
            np.full(dur - anos_area_escalonada, area_total)
        ])
    area_por_anio = np.pad(area_por_anio, (0, n_anios_default - len(area_por_anio)), constant_values=area_total)

    if tipo_captura == "lineal":
        cap_ini = sol["Captura Inicial"]
        cap_fin = sol["Captura Final"]
        cap_ha = np.linspace(cap_ini, cap_fin, dur)
    elif tipo_captura == "sigmoidal":
        cap_max = sol["Captura Máxima"]
        k = sol["Velocidad"]
        x0 = sol["Punto Medio"]
        x_vals = np.arange(dur)
        cap_ha = cap_max / (1 + np.exp(-k * (x_vals - x0)))
    else:
        cap_ha = np.full(dur, sol["Captura por ha (tCO2e)"])
    cap_ha = np.pad(cap_ha, (0, n_anios_default - len(cap_ha)), constant_values=0)

    salv = 1 - sol["Salvaguardas (%)"] / 100

    if tipo_sn == "degradacion":
        perdida_pct = sol.get("% Pérdida Evitada", 0.0) / 100
        area_efectiva = area_por_anio * perdida_pct
    else:
        area_efectiva = area_por_anio

    captura_anual = cap_ha * area_efectiva * salv

    costo_base = sol["Costo anual por ha (USD)"]
    costo_anual = np.array([
        costo_base * ((area_por_anio[i] / 100) ** -0.2) * area_por_anio[i]
        for i in range(n_anios_default)
    ])

    capex = sol["CAPEX Total (USD)"]
    ingreso_base = sol["Ingreso Encadenado (USD/año)"]

    gastos_adicionales = np.zeros(n_anios_default)
    for gasto in gastos_adicionales_comunes:
        if "anio" in gasto:
            if gasto["anio"] == -1:
                gastos_adicionales[0] += gasto["monto"] / (1 + tasa_descuento)
            elif 0 <= gasto["anio"] < n_anios_default:
                gastos_adicionales[gasto["anio"]] += gasto["monto"]
        elif "anio_cada" in gasto:
            desde = gasto.get("desde", 0)
            hasta = gasto.get("hasta", n_anios_default)
            for anio in range(desde, min(hasta + 1, n_anios_default)):
                if (anio - desde) % gasto["anio_cada"] == 0:
                    gastos_adicionales[anio] += gasto["monto"]

    monitoreo_en_campo = np.array([
        9.2 * area_por_anio[i] if i < dur else 0 for i in range(n_anios_default)
    ])

    flujo_proyecto = np.zeros(n_anios_default)
    flujo_proyecto[0] = -capex

    precio_base = precio_carbono * multiplicador_precio_carbono

    for anio in range(1, dur):
        ingreso = (
            captura_anual[anio] * precio_base * ((1 + crecimiento_precio_carbono) ** anio)
            + ingreso_base * ((1 + crecimiento_ingreso_encadenado) ** anio)
        )
        costo_total = costo_anual[anio]
        gasto_extra = gastos_adicionales[anio] + monitoreo_en_campo[anio]
        flujo_neto = ingreso - costo_total - gasto_extra
        if flujo_neto > 0:
            flujo_neto *= (1 - 0.15)
        flujo_proyecto[anio] = flujo_neto

    tasa_desc = tasa_descuento * multiplicador_tasa_descuento
    vpn = sum([
        flujo_proyecto[i] / ((1 + tasa_desc) ** (i + 1))
        for i in range(n_anios_default)
    ])

    return vpn, flujo_proyecto, captura_anual, area_por_anio, costo_anual, monitoreo_en_campo, gastos_adicionales

# --- CONFIGURAR PÁGINA ---
st.set_page_config(
    page_title="Sumideros Naturales de Carbono",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- TÍTULO DE CONTROL ---
st.title("🧪 Laboratorio de Pruebas")

# --- INICIALIZAR VARIABLES ---
resultados = []
df_resultados = pd.DataFrame()
flujo_total = np.zeros(30)

# --- ESTILOS ---
st.markdown("""
<style>
body {
    background-color: #f4f4f4;
}
section.main > div {
    padding-top: 1rem;
    padding-bottom: 1rem;
}
.css-18e3th9 {
    background-color: #ffffff;
    padding: 2rem;
    border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
footer {
    visibility: hidden;
}
</style>
""", unsafe_allow_html=True)

# --- ENCABEZADO ---
st.markdown("""
<div style="background-color: #F8F9FA; padding: 20px; border-radius: 10px; margin-bottom: 20px;">
    <div style="font-size: 28px; font-weight: bold; color: #003366;">📊 Sumideros Naturales de Carbono</div>
    <div style="font-size: 16px; color: #666666;">Modelo financiero para análisis de SNC`s</div>
</div>
""", unsafe_allow_html=True)

# --- SESSION STATE ---
if "soluciones" not in st.session_state:
    st.session_state["soluciones"] = []

# --- CONFIGURACIÓN GENERAL ---
st.sidebar.header("Parámetros Generales del Proyecto")
n_anios_default = 30
precio_carbono = st.sidebar.number_input("Precio del carbono (USD/ton CO2)", min_value=0.0, value=14.75, step=1.0)
# NUEVO: crecimiento anual del precio del carbono
crecimiento_precio_carbono = st.sidebar.slider(
    "Crecimiento Anual del Precio del Carbono (%)",
    min_value=0.0,
    max_value=15.0,
    value=4.97,
    step=0.5,
    help="Porcentaje de incremento anual del precio del carbono aplicado cada año"
) / 100
tasa_descuento = st.sidebar.slider("Tasa de descuento (%)", 1.0, 15.0, 12.0) / 100
#Crecimiento Anual del Ingreso por Encademiento Productivo
#st.sidebar.header("Crecimiento anual (sensibilidad)")

crecimiento_ingreso_encadenado = st.sidebar.slider(
    "Crecimiento anual de ingresos encadenamientos productivos (%)",
    min_value=0.0,
    max_value=15.0,
    value=1.5,
    step=1.0
) / 100

st.sidebar.header("Ajustes de Escenarios")
multiplicador_area = st.sidebar.slider("Multiplicador de Área (%)", 50, 150, 100, 10) / 100
multiplicador_precio_carbono = st.sidebar.slider("Multiplicador Precio Carbono (%)", 50, 150, 100, 10) / 100
multiplicador_tasa_descuento = st.sidebar.slider("Multiplicador Tasa Descuento (%)", 50, 150, 100, 10) / 100

# --- CARGA O FORMULARIO de SNC del Estudio ---
st.sidebar.header("Modelación de SNCs")

if st.sidebar.button("Resetear Modelo"):
    st.session_state.soluciones = []
    st.rerun()

opcion_fuente = st.sidebar.radio("Ingreso de soluciones", ("Subir archivo Excel", "Modelación Interactiva"))

if opcion_fuente.strip().lower() == "subir archivo excel":
    archivo = st.sidebar.file_uploader("Sube archivo .xlsx", type=["xlsx"])
    if archivo:
        try:
            df_soluciones = pd.read_excel(archivo)
            columnas_esperadas = [
                "Solución", "Área (ha)", "Costo anual por ha (USD)", "CAPEX Total (USD)",
                "Duración (años)", "Salvaguardas (%)", "Ingreso Encadenado (USD/año)",
                "Tipo Captura", "Tipo SNC", "% Pérdida Evitada",
                "Captura por ha (tCO2e)", "Captura Inicial", "Captura Final",
                "Captura Máxima", "Velocidad", "Punto Medio",
                "Escalonada", "Años Escalonamiento"
            ]

            columnas_presentes = df_soluciones.columns.tolist()
            faltantes = [col for col in columnas_esperadas if col not in columnas_presentes]

            if faltantes:
                st.error(f"⚠️ Faltan las siguientes columnas en el archivo: {faltantes}")
                df_soluciones = pd.DataFrame()  # Vacía para evitar errores posteriores
            else:
                soluciones = []
                for _, row in df_soluciones.iterrows():
                    try:
                        tipo_captura = row.get("Tipo Captura", "constante")
                        tipo_sn = row.get("Tipo SNC", "restauracion")
                        escalonada = bool(row.get("Escalonada", False))
                        anios_escalonamiento = int(row.get("Años Escalonamiento", 1))

                        nueva = {
                            "Solución": str(row["Solución"]),
                            "Área (ha)": float(row["Área (ha)"]),
                            "Costo anual por ha (USD)": float(row["Costo anual por ha (USD)"]),
                            "CAPEX Total (USD)": float(row["CAPEX Total (USD)"]),
                            "Duración (años)": int(row["Duración (años)"]),
                            "Salvaguardas (%)": float(row["Salvaguardas (%)"]),
                            "Ingreso Encadenado (USD/año)": float(row["Ingreso Encadenado (USD/año)"]),
                            "Tipo Captura": tipo_captura,
                            "Tipo SNC": tipo_sn,
                            "% Pérdida Evitada": float(row.get("% Pérdida Evitada", 0)),
                            "Escalonada": escalonada,
                            "Años Escalonamiento": anios_escalonamiento
                        }

                        if tipo_captura == "constante":
                            nueva["Captura por ha (tCO2e)"] = float(row["Captura por ha (tCO2e)"])
                        elif tipo_captura == "lineal":
                            nueva["Captura Inicial"] = float(row["Captura Inicial"])
                            nueva["Captura Final"] = float(row["Captura Final"])
                        elif tipo_captura == "sigmoidal":
                            nueva["Captura Máxima"] = float(row["Captura Máxima"])
                            nueva["Velocidad"] = float(row["Velocidad"])
                            nueva["Punto Medio"] = int(row["Punto Medio"])

                        soluciones.append(nueva)
                    except Exception as e:
                        st.warning(f"❗ Error procesando una solución: {e}")

                if soluciones:
                    st.session_state.soluciones.extend(soluciones)
                    st.success(f"✅ Se cargaron correctamente {len(soluciones)} solución(es) desde el archivo.")
                else:
                    st.warning("⚠️ No se encontraron soluciones válidas en el archivo.")

        except Exception as e:
            st.error(f"❌ Error al leer el archivo: {str(e)}")

#if opcion_fuente.strip().lower() == "subir archivo excel":
#    archivo = st.sidebar.file_uploader("Sube archivo .xlsx", type=["xlsx"])
    df_soluciones = pd.read_excel(archivo) if archivo else pd.DataFrame()

else:
    # Diccionario base de soluciones
    soluciones_predeterminadas = {
        "Pastos Marinos": {"captura": 7.5, "costo": 70, "duracion": 30, "capex": 500, "tipo_captura": "constante", "tipo_sn": "restauracion"},
        "Manglares": {"captura": 10, "costo": 90, "duracion": 30, "capex": 800, "tipo_captura": "constante", "tipo_sn": "restauracion"},
        "Bosque Seco Tropical": {"captura": 6, "costo": 55, "duracion": 25, "capex": 400, "tipo_captura": "constante", "tipo_sn": "restauracion"},
        "Corales": {"captura": 3, "costo": 100, "duracion": 20, "capex": 1500, "tipo_captura": "constante", "tipo_sn": "restauracion"},
        "Agroforestería con Cacao": {"captura": 5, "costo": 50, "duracion": 20, "capex": 300, "tipo_captura": "constante", "tipo_sn": "restauracion"},
        "Bosque de Galería": {"captura": 8, "costo": 65, "duracion": 30, "capex": 600, "tipo_captura": "constante", "tipo_sn": "restauracion"},
        "Turberas Andinas": {"captura": 5, "costo": 70, "duracion": 30, "capex": 750, "tipo_captura": "constante", "tipo_sn": "restauracion"},

        "Restauración de Pastos Degradados": {
            "tipo_captura": "lineal", "captura_inicial": 2.0, "captura_final": 6.0,
            "costo": 40, "duracion": 30, "capex": 300, "tipo_sn": "restauracion"
        },
        "Reforestación Productiva Zonas ECP": {
            "tipo_captura": "lineal", "captura_inicial": 1.5, "captura_final": 5.5,
            "costo": 60, "duracion": 30, "capex": 350, "tipo_sn": "restauracion"
        },
        "Restauración de Manglares Caribe (Esp.)": {
            "tipo_captura": "sigmoidal", "captura_max": 8.0, "velocidad": 0.3, "punto_medio": 15,
            "costo": 80, "duracion": 30, "capex": 900, "tipo_sn": "restauracion"
        },

        "Manglar Degradación Evitada": {"captura": 8.0, "costo": 60, "duracion": 30, "capex": 400, "tipo_captura": "constante", "tipo_sn": "degradacion"},
        "Manglar Degradación Evitada (2)": {"captura": 8.0, "costo": 60, "duracion": 30, "capex": 400, "tipo_captura": "constante", "tipo_sn": "degradacion"},
        "Bosque Húmedo Degradación Evitada": {"captura": 7.0, "costo": 50, "duracion": 30, "capex": 350, "tipo_captura": "constante", "tipo_sn": "degradacion"},
        "Bosque Húmedo Degradación Evitada (2)": {"captura": 7.0, "costo": 50, "duracion": 30, "capex": 350, "tipo_captura": "constante", "tipo_sn": "degradacion"},
        "Páramo Degradación Evitada": {"captura": 5.5, "costo": 55, "duracion": 30, "capex": 370, "tipo_captura": "constante", "tipo_sn": "degradacion"},
        "Páramo Degradación Evitada (2)": {"captura": 5.5, "costo": 55, "duracion": 30, "capex": 370, "tipo_captura": "constante", "tipo_sn": "degradacion"},
        "Humedal Degradación Evitada": {"captura": 6.5, "costo": 60, "duracion": 30, "capex": 390, "tipo_captura": "constante", "tipo_sn": "degradacion"},
        "Humedal Degradación Evitada (2)": {"captura": 6.5, "costo": 60, "duracion": 30, "capex": 390, "tipo_captura": "constante", "tipo_sn": "degradacion"},
        "Humedal Degradación Evitada (3)": {"captura": 6.5, "costo": 60, "duracion": 30, "capex": 390, "tipo_captura": "constante", "tipo_sn": "degradacion"},
        "Pastos Degradación Evitada": {"captura": 4.5, "costo": 40, "duracion": 30, "capex": 310, "tipo_captura": "constante", "tipo_sn": "degradacion"},
        "Pastos Degradación Evitada (2)": {"captura": 4.5, "costo": 40, "duracion": 30, "capex": 310, "tipo_captura": "constante", "tipo_sn": "degradacion"}
    }

    # Selector dinámico
    tipo_sol = st.sidebar.selectbox("Tipo de solución", list(soluciones_predeterminadas))
    base = soluciones_predeterminadas[tipo_sol]

    # Iniciar formulario
    with st.sidebar.form("form_solucion"):
        area = st.number_input("Área (ha)", 0.0, value=100.0)
        escalonada = st.checkbox("¿SNC escalonada en el tiempo?", value=False)
        anios_escalonamiento = st.slider("Años para completar el 100% del área", 1, 30, 3) if escalonada else 1

        costo = st.number_input("Costo anual USD/ha", 0.0, value=float(base["costo"]))
        capex = st.number_input("CAPEX Total (USD)", 0.0, value=float(base["capex"]))
        duracion = st.number_input("Duración (años)", 1, 50, int(base["duracion"]))
        salvaguarda = st.number_input("Salvaguardas %", 0.0, 100.0, 0.0)
        ingreso_extra = st.number_input("Ingreso Encadenamiento Productivo USD/año", 0.0, value=0.0)

        tipo_captura = base.get("tipo_captura", "constante")
        tipo_sn = base.get("tipo_sn", "restauracion")

        if tipo_captura == "constante":
            captura = st.number_input("Captura ó Emisión Evitada CO2eq. ha/año", 0.0, value=float(base["captura"]))
        elif tipo_captura == "lineal":
            captura_inicial = st.number_input("Captura Inicial CO2eq. ha/año", 0.0, value=float(base["captura_inicial"]))
            captura_final = st.number_input("Captura Final CO2eq. ha/año", 0.0, value=float(base["captura_final"]))
        elif tipo_captura == "sigmoidal":
            captura_max = st.number_input("Captura Máxima ha/año", 0.0, value=float(base["captura_max"]))
            velocidad = st.number_input("Velocidad de Captura", 0.01, 5.0, value=float(base["velocidad"]))
            punto_medio = st.number_input("Año Punto Medio", 1, 50, int(base["punto_medio"]))

        if tipo_sn == "degradacion":
            perdida_evitada = st.number_input("% Pérdida Evitada", 0.0, 100.0, 3.5)
        else:
            perdida_evitada = 0.0

        submit = st.form_submit_button("Agregar Solución")

        if submit:
            nueva = {
                "Solución": tipo_sol,
                "Área (ha)": area,
                "Costo anual por ha (USD)": costo,
                "CAPEX Total (USD)": capex,
                "Duración (años)": duracion,
                "Salvaguardas (%)": salvaguarda,
                "Ingreso Encadenado (USD/año)": ingreso_extra,
                "Tipo Captura": tipo_captura,
                "Tipo SNC": tipo_sn,
                "% Pérdida Evitada": perdida_evitada,
                "Escalonada": escalonada,
                "Años Escalonamiento": anios_escalonamiento
            }

            if tipo_captura == "constante":
                nueva["Captura por ha (tCO2e)"] = captura
            elif tipo_captura == "lineal":
                nueva["Captura Inicial"] = captura_inicial
                nueva["Captura Final"] = captura_final
            elif tipo_captura == "sigmoidal":
                nueva["Captura Máxima"] = captura_max
                nueva["Velocidad"] = velocidad
                nueva["Punto Medio"] = punto_medio

            st.session_state.soluciones.append(nueva)

    df_soluciones = pd.DataFrame(st.session_state.soluciones)

# --- MOSTRAR TABLA DE ENTRADA ---
st.subheader("Soluciones Climáticas Actuales")
if not df_soluciones.empty:
    st.dataframe(df_soluciones)
else:
    st.info("Agrega soluciones para comenzar.")

# --- CÁLCULO DE RESULTADOS ---
st.subheader("Resultados de Modelación")

if not df_soluciones.empty:
    resultados = []
    flujo_total = np.zeros(n_anios_default)
    #st.write("Columnas actuales:", df_soluciones.columns.tolist())

    for _, sol in df_soluciones.iterrows():
        dur = int(sol["Duración (años)"])
        area_total = sol["Área (ha)"] * multiplicador_area
        tipo_captura = sol.get("Tipo Captura", "constante")
        tipo_sn = sol.get("Tipo SNC", "restauracion")
        anos_area_escalonada = sol.get("Años para 100% área", 1)

        # --- Distribución escalonada del área
        if anos_area_escalonada == 1:
            area_por_anio = np.full(dur, area_total)
        else:
            area_por_anio = np.concatenate([
                np.linspace(area_total / anos_area_escalonada, area_total, anos_area_escalonada),
                np.full(dur - anos_area_escalonada, area_total)
            ])
        area_por_anio = np.pad(area_por_anio, (0, n_anios_default - len(area_por_anio)), constant_values=area_total)

        # --- Cálculo de captura por ha según tipo
        if tipo_captura == "lineal":
            cap_ini = soluciones_predeterminadas[sol["Solución"]]["captura_inicial"]
            cap_fin = soluciones_predeterminadas[sol["Solución"]]["captura_final"]
            cap_ha = np.linspace(cap_ini, cap_fin, dur)
        elif tipo_captura == "sigmoidal":
            cap_max = soluciones_predeterminadas[sol["Solución"]]["captura_max"]
            k = soluciones_predeterminadas[sol["Solución"]]["velocidad"]
            x0 = soluciones_predeterminadas[sol["Solución"]]["punto_medio"]
            x_vals = np.arange(dur)
            cap_ha = cap_max / (1 + np.exp(-k * (x_vals - x0)))
        else:  # constante
            cap_ha_valor = sol["Captura por ha (tCO2e)"]
            cap_ha = np.full(dur, cap_ha_valor)

        cap_ha = np.pad(cap_ha, (0, n_anios_default - len(cap_ha)), constant_values=0)

        # --- Salvaguarda como descuento de riesgo
        salv = 1 - sol["Salvaguardas (%)"] / 100

        # --- Validar pérdida evitada con protección de formato
        perdida_raw = sol.get("% Pérdida Evitada", sol.get("Pérdida Evitada (%)", 0.0))
        perdida_str = str(perdida_raw).replace(",", ".")  # Por si viene como "3,88"
        try:
            perdida_pct = float(perdida_str) / 100
        except ValueError:
            perdida_pct = 0.0

        #st.write(f"🧪 Valor crudo de pérdida evitada: {perdida_raw}")
        #st.write(f"🧪 Interpretado como proporción: {perdida_pct:.4f} ({perdida_pct*100:.2f}%)")

        # --- Cálculo de captura anual según tipo de SNC
        if tipo_sn == "degradacion":
            area_evitable_por_anio = area_por_anio * perdida_pct

            # IMPRESIONES DE DEPURACIÓN CLAVE
            #st.markdown("#### 🔍 Verificación de Cálculo de Degradación Evitada")
            #st.write(f"Área total declarada: {area_total}")
            #st.write(f"Pérdida evitada (proporción): {perdida_pct}")
            #st.write(f"Área evitable primer año: {area_evitable_por_anio[0]}")
            #st.write(f"Captura por ha primer año: {cap_ha[0]}")
            #st.write(f"Salvaguarda aplicada (1 - {sol['Salvaguardas (%)']}%): {salv}")
            #st.write(f"Captura estimada año 1: {area_evitable_por_anio[0] * cap_ha[0] * salv}")

            captura_anual = area_evitable_por_anio * cap_ha * salv
        else:
            captura_anual = area_por_anio * cap_ha * salv

        captura_total = sum(captura_anual)

        # === DEPURACIÓN TEMPORAL ===
        #st.markdown(f"### 🧪 Solución: {sol['Solución']}")
        #st.write("Área por año:", area_por_anio.tolist())
        #st.write("Captura por ha:", cap_ha.tolist())
        #st.write("Captura anual:", captura_anual.tolist())
        #st.write("Captura total estimada (tCO₂e):", captura_total)
        # === Gráfico: Captura acumulada de carbono por solución + total ===
        st.markdown("### 📈 Captura Acumulada de Carbono por Solución y Total")

        data_acumulada = []

        for _, sol in df_soluciones.iterrows():
            nombre = sol["Solución"]
            dur = int(sol["Duración (años)"])
            area_total = sol["Área (ha)"] * multiplicador_area
            tipo = sol.get("Tipo Captura", "constante")
            tipo_sn = sol.get("Tipo SNC", "restauracion")
            anos_area_escalonada = sol.get("Años para 100% área", 1)
            salvaguarda = 1 - sol.get("Salvaguardas (%)", 0.0) / 100
            perdida_pct = sol.get("% Pérdida Evitada", sol.get("Pérdida Evitada (%)", 0.0)) / 100

            # Área escalonada
            if anos_area_escalonada == 1:
                area_por_anio = np.full(dur, area_total)
            else:
                area_por_anio = np.concatenate([
                    np.linspace(area_total / anos_area_escalonada, area_total, anos_area_escalonada),
                    np.full(dur - anos_area_escalonada, area_total)
                ])
            area_por_anio = np.pad(area_por_anio, (0, n_anios_default - len(area_por_anio)), constant_values=area_total)

            # Captura por ha según tipo
            if tipo == "lineal":
                cap_ini = sol.get("Captura Inicial", 0.0)
                cap_fin = sol.get("Captura Final", 0.0)
                captura_ha = np.linspace(cap_ini, cap_fin, dur)
            elif tipo == "sigmoidal":
                cap_max = sol.get("Captura Máxima", 0.0)
                k = sol.get("Velocidad", 1.0)
                x0 = sol.get("Punto Medio", dur // 2)
                x_vals = np.arange(dur)
                captura_ha = cap_max / (1 + np.exp(-k * (x_vals - x0)))
            else:
                cap_ha_val = sol.get("Captura por ha (tCO2e)", 0.0)
                captura_ha = np.full(dur, cap_ha_val)

            captura_ha = np.pad(captura_ha, (0, n_anios_default - len(captura_ha)), constant_values=0)

            acumulado = 0
            for anio in range(n_anios_default):
                if tipo_sn == "degradacion":
                    area_efectiva = area_por_anio[anio] * perdida_pct
                else:
                    area_efectiva = area_por_anio[anio]

                captura_anual = captura_ha[anio] * area_efectiva * salvaguarda
                acumulado += captura_anual

                data_acumulada.append({
                    "Año": anio + 1,
                    "Solución": nombre,
                    "Captura Acumulada": acumulado
                })

        # Convertir a DataFrame
        df_acumulada = pd.DataFrame(data_acumulada)

        # Agregar total
        if not df_acumulada.empty and "Año" in df_acumulada.columns:
            df_total_acum = df_acumulada.groupby("Año")["Captura Acumulada"].sum().reset_index()
            df_total_acum["Solución"] = "Total Portafolio"
            df_graf = pd.concat([df_acumulada, df_total_acum], ignore_index=True)

            # Graficar
            fig_acum = px.line(
                df_graf,
                x="Año",
                y="Captura Acumulada",
                color="Solución",
                title="📈 Captura de Carbono Acumulada por Solución y Total",
                labels={"Captura Acumulada": "Toneladas CO₂e"}
            )
            fig_acum.update_layout(
                xaxis_title="Año del Proyecto",
                yaxis_title="Carbono Acumulado (tCO₂e)",
                plot_bgcolor="white",
                margin=dict(t=50, b=40),
                legend_title="Solución"
            )
            st.plotly_chart(fig_acum, use_container_width=True, key=f"plot_acumulada_{uuid.uuid4()}")
        else:
            st.warning("⚠️ No hay datos suficientes para mostrar la captura acumulada. Agrega al menos una solución.")

        # === Cálculo financiero ===
        # Definir gastos adicionales comunes por solución
        gastos_adicionales_comunes = [
            {"descripcion": "Estudio base", "monto": 50000, "anio": -2},
            {"descripcion": "Estudio base", "monto": 50000, "anio": -1},
            {"descripcion": "Estudio base", "monto": 25000, "anio": 1},
            {"descripcion": "Estudio base", "monto": 20000, "anio": 2},
            {"descripcion": "Estudio base", "monto": 10000, "anio": 3},
            {"descripcion": "Imprevistos", "monto": 3000, "anio_cada": 1, "desde": 0, "hasta": 15},
            {"descripcion": "CostosTransaccion", "monto": 30000, "anio_cada": 3, "desde": 1, "hasta": 19},
        ]
        
        resultados = []
        flujo_total = np.zeros(n_anios_default)

        for _, sol in df_soluciones.iterrows():
            vpn, flujo_proyecto, captura_anual, area_por_anio, costo_anual, monitoreo_en_campo, gastos_adicionales = calcular_vpn_solucion(
                sol,
                tasa_descuento,
                n_anios_default,
                gastos_adicionales_comunes,
                precio_carbono,
                multiplicador_precio_carbono,
                crecimiento_precio_carbono,
                crecimiento_ingreso_encadenado
            )

            flujo_total += flujo_proyecto

            captura_total = sum(captura_anual)
            capex = sol["CAPEX Total (USD)"]
            ingreso_base = sol["Ingreso Encadenado (USD/año)"]
            precio_base = precio_carbono * multiplicador_precio_carbono

            ingreso_carbono = sum([
                captura_anual[i] * (precio_base * ((1 + crecimiento_precio_carbono) ** i))
                for i in range(len(captura_anual))
            ])
            ingreso_encadenado = sum([
                ingreso_base * ((1 + crecimiento_ingreso_encadenado) ** i)
                for i in range(len(captura_anual))
            ])
            ingreso_total = ingreso_carbono + ingreso_encadenado

            resultados.append({
                "Solución": sol["Solución"],
                "Área (ha)": sol["Área (ha)"] * multiplicador_area,
                "Carbono Total (tCO2e)": captura_total,
                "Costo Total (USD)": sum(costo_anual),
                "CAPEX Total (USD)": capex,
                "Ingreso Total (USD)": ingreso_total,
                "VPN (USD)": vpn
            })

            df_tabla_financiera = pd.DataFrame({
                "Año": np.arange(1, n_anios_default + 1),
                "Área aplicada (ha)": np.round(area_por_anio, 2),
                "Captura anual (tCO₂e)": np.round(captura_anual, 2),
                "Ingreso carbono (USD)": [
                    round(captura_anual[i] * precio_base * ((1 + crecimiento_precio_carbono) ** i), 2)
                    if i < len(captura_anual) else 0 for i in range(n_anios_default)
                ],
                "Ingreso encadenado (USD)": [
                    round(ingreso_base * ((1 + crecimiento_ingreso_encadenado) ** i), 2)
                    if i < len(captura_anual) else 0 for i in range(n_anios_default)
                ],
                "OPEX ajustado (USD)": np.round(costo_anual, 2),
                "Monitoreo campo (USD)": np.round(monitoreo_en_campo, 2),
                "Gastos adicionales (USD)": np.round(gastos_adicionales, 2),
                "Flujo neto (USD)": np.round(flujo_proyecto, 2)
            })

            st.subheader(f"🔍 Flujo de Caja Año a Año para: {sol['Solución']}")
            st.dataframe(df_tabla_financiera)

        # Crear dataframe final
        df_resultados = pd.DataFrame(resultados)
        
# --- Flujo de Caja Acumulado ---
anios = np.arange(1, n_anios_default + 1)
flujo_caja_acumulado = np.cumsum(flujo_total)  # 👈 Esta línea es clave

# Crear DataFrame
df_flujo = pd.DataFrame({
    "Año": anios,
    "Flujo de Caja Acumulado": flujo_caja_acumulado
})

# Crear gráfico
fig_flujo = px.line(
    df_flujo,
    x="Año",
    y="Flujo de Caja Acumulado",
    markers=True,
    title="Evolución del Flujo de Caja Acumulado",
    labels={"Flujo de Caja Acumulado": "USD"}
)

fig_flujo.update_layout(
    xaxis_title="Año del Proyecto",
    yaxis_title="USD Acumulado",
    plot_bgcolor='white',
    margin=dict(t=50, b=50)
)

# Mostrar
st.markdown("### 🔎 Verificación de Datos para Gráficas")
st.dataframe(df_flujo)
st.plotly_chart(fig_flujo, use_container_width=True)

# --- Matriz Comparativa (RECONSTRUIDA y BLINDADA) ---
matriz_comparativa = []

for _, sol in df_soluciones.iterrows():
    try:
        vpn, flujo_proyecto, captura_anual, area_por_anio, costo_anual, monitoreo_en_campo, gastos_adicionales = calcular_vpn_solucion(
            sol,
            tasa_descuento,
            n_anios_default,
            gastos_adicionales_comunes,
            precio_carbono,
            multiplicador_precio_carbono,
            crecimiento_precio_carbono,
            crecimiento_ingreso_encadenado
        )

        area_total = sol["Área (ha)"] * multiplicador_area
        carbono_total = sum(captura_anual)
        costo_total = sum(costo_anual)

        matriz_comparativa.append({
            "Solución": sol["Solución"],
            "Área (ha)": area_total,
            "Carbono Total (tCO2e)": carbono_total,
            "VPN (USD)": vpn,
            "Costo Total (USD)": costo_total,
            "Eficiencia CO₂e/ha": carbono_total / area_total if area_total > 0 else 0,
            "Eficiencia VPN/ha": vpn / area_total if area_total > 0 else 0
        })
        # --- TRAZABILIDAD: mostrar datos clave para depurar diferencias de VPN ---
        st.markdown(f"#### Trazabilidad: {sol['Solución']}")
        st.code(f"""
        Área total (ha): {area_total}
        Carbono total (tCO2e): {carbono_total}
        VPN (USD): {vpn}
        Costo total (USD): {costo_total}
        Tasa de descuento aplicada: {tasa_descuento}
        Precio del carbono (USD/tCO2e): {precio_carbono}
        Multiplicador precio carbono: {multiplicador_precio_carbono}
        Crecimiento precio carbono: {crecimiento_precio_carbono}
        Ingreso encadenado: {sol.get('Ingreso Encadenado (USD/año)', 0)}
        Salvaguardas (%): {sol.get('Salvaguardas (%)', 0)}
        % Pérdida evitada: {sol.get('% Pérdida Evitada', sol.get('Pérdida Evitada (%)', 0))}
        """)
    except Exception as e:
        st.error(f"❌ Error al procesar la solución '{sol.get('Solución', 'N/A')}': {e}")

# Validar si hubo resultados
if not matriz_comparativa:
    st.warning("⚠️ No se pudo generar la matriz comparativa. Revisa los datos de entrada.")
else:
    df_comparativa = pd.DataFrame(matriz_comparativa)
    df_comparativa.iloc[:, 1:] = df_comparativa.iloc[:, 1:].round(2)

    # Validar columnas para estilos
    columnas_estilo = []
    if "Eficiencia CO₂e/ha" in df_comparativa.columns:
        columnas_estilo.append("Eficiencia CO₂e/ha")
    if "Eficiencia VPN/ha" in df_comparativa.columns:
        columnas_estilo.append("Eficiencia VPN/ha")

    st.markdown("### 📊 Matriz Comparativa de Eficiencia por Solución")
    st.dataframe(
        df_comparativa.style
            .background_gradient(cmap="YlGnBu", subset=columnas_estilo)
            .format({col: "{:,.2f}" for col in df_comparativa.columns if col != "Solución"})
    )

st.markdown("## 📊 Heatmaps de Sensibilidad por Solución Individual")

for _, sol in df_soluciones.iterrows():
    nombre_solucion = sol['Solución']
    st.markdown(f"### 🔹 {nombre_solucion}")

    rango_precio = np.arange(5, 51, 5)
    rango_descuento = np.arange(1, 22, 1)
    matriz_vpn_individual = np.zeros((len(rango_descuento), len(rango_precio)))

    for i, td in enumerate(rango_descuento):
        for j, pc in enumerate(rango_precio):
            tasa = td / 100
            try:
                vpn, _, _, _, _, _, _ = calcular_vpn_solucion(
                    sol,
                    tasa,
                    n_anios_default,
                    gastos_adicionales_comunes,
                    pc,
                    multiplicador_precio_carbono,
                    crecimiento_precio_carbono,
                    crecimiento_ingreso_encadenado
                )
                matriz_vpn_individual[i, j] = vpn
            except Exception as e:
                matriz_vpn_individual[i, j] = np.nan  # o 0 si prefieres

    zmax_manual = 1000000  # ajustar a criterio

    fig = go.Figure(
        data=go.Heatmap(
            z=matriz_vpn_individual,
            x=rango_precio,
            y=rango_descuento,
            zmin=0,
            zmax=zmax_manual,
            colorscale='Viridis',
            colorbar=dict(
                title="VPN (USD)",
                tickformat=",",
                ticksuffix="",
                exponentformat="none"
            )
        )
    )

    fig.update_layout(
        title=f"🌡️ Sensibilidad del VPN – {nombre_solucion}",
        xaxis_title="Precio del Carbono (USD/tCO₂e)",
        yaxis_title="Tasa de Descuento (%)",
        margin=dict(l=40, r=40, t=60, b=40)
    )

    st.plotly_chart(fig, use_container_width=True)

# --- Heatmap de Sensibilidad del VPN (USANDO FUNCIÓN CENTRAL UNIFICADA) ---
rango_precio = np.arange(5, 51, 5)
rango_descuento = np.arange(1, 22, 1)
matriz_vpn = np.zeros((len(rango_descuento), len(rango_precio)))

for i, td in enumerate(rango_descuento):
    for j, pc in enumerate(rango_precio):
        tasa = td / 100
        vpn_total = 0

        for _, sol in df_soluciones.iterrows():
            vpn, _, _, _, _, _, _ = calcular_vpn_solucion(
                sol,
                tasa,
                n_anios_default,
                gastos_adicionales_comunes,
                pc,  # precio del carbono (variable del heatmap)
                multiplicador_precio_carbono,
                crecimiento_precio_carbono,
                crecimiento_ingreso_encadenado
            )
            # Trazabilidad solo para el punto base (tasa = 12%, precio = 14.75)
            if abs(tasa - 0.12) < 1e-6 and abs(pc - 14.75) < 1e-3:
                st.markdown(f"#### 🧮 Heatmap VPN Individual – Solución: {sol['Solución']}")
                st.code(f"""
            VPN (USD): {vpn:,.2f}
            Área total (ha): {sol["Área (ha)"] * multiplicador_area}
            Captura por ha (tCO2e): {sol.get("Captura por ha (tCO2e)", "-")}
            Ingreso encadenado (USD/año): {sol.get("Ingreso Encadenado (USD/año)", 0)}
            Salvaguardas (%): {sol.get("Salvaguardas (%)", 0)}
            Pérdida evitada (%): {sol.get("% Pérdida Evitada", sol.get("Pérdida Evitada (%)", 0))}
            Tipo SNC: {sol.get("Tipo SNC", "-")}
            Tipo Captura: {sol.get("Tipo Captura", "-")}
                """)
            vpn_total += vpn

        matriz_vpn[i, j] = vpn_total

# Gráfico
# Crear heatmap base
fig_heat = go.Figure()

fig_heat.add_trace(go.Heatmap(
    z=matriz_vpn,
    x=rango_precio,
    y=rango_descuento,
    colorscale='Viridis',
    colorbar=dict(
    title="VPN (USD)",
    tickformat=",",            # separador de miles
    ticksuffix="",             # sin sufijo adicional
    exponentformat="none",     # sin notación científica
    ),
    name="VPN calculado"
))

# 🔵 Agregar punto base (tasa = 12%, precio = 14.75 USD)
# Recalcular VPN exacto para ese punto
vpn_base_visual = 0
for _, sol in df_soluciones.iterrows():
    vpn, _, _, _, _, _, _ = calcular_vpn_solucion(
        sol,
        0.12,
        n_anios_default,
        gastos_adicionales_comunes,
        14.75,
        multiplicador_precio_carbono,
        crecimiento_precio_carbono,
        crecimiento_ingreso_encadenado
    )
    vpn_base_visual += vpn


# Layout general
fig_heat.update_layout(
    title="🌡️ Sensibilidad del VPN – Precio del Carbono vs Tasa de Descuento",
    xaxis_title="Precio del Carbono (USD/tCO₂e)",
    yaxis_title="Tasa de Descuento (%)",
    margin=dict(l=40, r=40, t=60, b=40)
)
st.write("🔢 Valor máximo en matriz VPN:", np.max(matriz_vpn))
st.plotly_chart(fig_heat, use_container_width=True)

st.markdown("### 🧪 Verificación Manual del Caso Base (14.75 USD, 12%)")

vpn_total_manual = 0

for _, sol in df_soluciones.iterrows():
    vpn, _, _, _, _, _, _ = calcular_vpn_solucion(
        sol,
        0.12,             # tasa de descuento
        n_anios_default,
        gastos_adicionales_comunes,
        14.75,            # precio del carbono
        multiplicador_precio_carbono,
        crecimiento_precio_carbono,
        crecimiento_ingreso_encadenado
    )

    vpn_total_manual += vpn

    st.markdown(f"#### 🔍 Solución: {sol['Solución']}")
    st.code(f'''
VPN individual: {vpn}
Área total (ha): {sol["Área (ha)"] * multiplicador_area}
Ingreso encadenado (USD/año): {sol.get("Ingreso Encadenado (USD/año)", 0)}
Salvaguardas (%): {sol.get("Salvaguardas (%)", 0)}
% Pérdida evitada: {sol.get("% Pérdida Evitada", sol.get("Pérdida Evitada (%)", 0))}
Tipo Captura: {sol.get("Tipo Captura", "-")}
Tipo SNC: {sol.get("Tipo SNC", "-")}
''')

st.success(f"✅ VPN total acumulado para el caso base (14.75 USD, 12%): {vpn_total_manual:,.2f}")

# --- Comparación de Escenarios VPN (Corregido con función central) ---
precios = [precio_carbono * 0.8, precio_carbono, precio_carbono * 1.2]
etiquetas = ["Bajo", "Caso Base", "Alto"]
df_escenarios_plot = []

for i, p in enumerate(precios):
    for _, sol in df_soluciones.iterrows():
        try:
            vpn, _, _, _, _, _, _ = calcular_vpn_solucion(
                sol,
                tasa_descuento,  # O ajustada si tú decides aplicarla
                n_anios_default,
                gastos_adicionales_comunes,
                p,  # Precio del carbono del escenario
                multiplicador_precio_carbono,
                crecimiento_precio_carbono,
                crecimiento_ingreso_encadenado
            )

            df_escenarios_plot.append({
                "Solución": sol["Solución"],
                "VPN": vpn,
                "Escenario": etiquetas[i]
            })

        except Exception as e:
            st.error(f"❌ Error en solución '{sol.get('Solución', 'N/A')}' – Escenario {etiquetas[i]}: {e}")

# Convertir a DataFrame y graficar
df_escenarios_plot = pd.DataFrame(df_escenarios_plot)

if not df_escenarios_plot.empty and all(col in df_escenarios_plot.columns for col in ["Solución", "VPN", "Escenario"]):
    fig_escenarios = px.bar(
        df_escenarios_plot,
        x="Solución",
        y="VPN",
        color="Escenario",
        barmode="group",
        text="VPN",
        title="📊 VPN por Solución en Tres Escenarios de Precio del Carbono (±20%)",
        labels={"VPN": "Valor Presente Neto (USD)"}
    )
    fig_escenarios.update_traces(texttemplate='%{text:,.0f}', textposition='outside')
    fig_escenarios.update_layout(
        xaxis_title=None,
        yaxis_title="VPN (USD)",
        plot_bgcolor='white',
        margin=dict(t=50, b=50)
    )
    st.plotly_chart(fig_escenarios, use_container_width=True)
else:
    st.info("⚠️ No hay datos suficientes para mostrar el gráfico de comparación de escenarios.")

# --- Visualización 3D (Coherente con el modelo) ---
data_3d = []

for _, sol in df_soluciones.iterrows():
    try:
        vpn, flujo_proyecto, captura_anual, area_por_anio, _, _, _ = calcular_vpn_solucion(
            sol,
            tasa_descuento,  # o ajustada si quieres
            n_anios_default,
            gastos_adicionales_comunes,
            precio_carbono,
            multiplicador_precio_carbono,
            crecimiento_precio_carbono,
            crecimiento_ingreso_encadenado
        )

        carbono_total = np.sum(captura_anual)
        area_total = np.sum(area_por_anio)

        data_3d.append({
            "Solución": sol["Solución"],
            "Área (ha)": area_total,
            "Carbono Total (tCO2e)": carbono_total,
            "VPN (USD)": vpn
        })

    except Exception as e:
        st.error(f"❌ Error en solución '{sol.get('Solución', 'N/A')}': {e}")

# Convertir y graficar
df_3d = pd.DataFrame(data_3d)

if not df_3d.empty:
    fig3d = px.scatter_3d(
        df_3d,
        x="Carbono Total (tCO2e)",
        y="VPN (USD)",
        z="Área (ha)",
        color="Solución",
        hover_name="Solución",
        size="Área (ha)",
        title="🔵 Análisis 3D: Carbono, Rentabilidad y Escala",
        labels={
            "Carbono Total (tCO2e)": "Carbono (tCO2e)",
            "VPN (USD)": "Valor Presente Neto (USD)",
            "Área (ha)": "Área (ha)"
        }
    )
    fig3d.update_layout(margin=dict(l=0, r=0, b=0, t=40))
    st.plotly_chart(fig3d, use_container_width=True)
else:
    st.info("No hay datos para visualizar el gráfico 3D.")

    

#Exportación de Resultados a PDF
import streamlit.components.v1 as components

#st.markdown("Descargar la modelación como PDF")

components.html("""
    <html>
    <head>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/jspdf/2.5.1/jspdf.umd.min.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
    </head>
    <body>
        <button onclick="exportarTodo()" style="padding:12px 24px; font-size:14px; background:#f8f9fa; color:grey; border:none; border-radius:8px;">
            📥 Descargar Modelación Completa en PDF
        </button>

        <script>
        async function exportarTodo() {
            const { jsPDF } = window.jspdf;
            const doc = new jsPDF('p', 'pt', 'a4');
            const body = document.body;

            await html2canvas(body, { scale: 2 }).then(canvas => {
                const imgData = canvas.toDataURL("image/png");
                const imgProps = doc.getImageProperties(imgData);
                const pdfWidth = doc.internal.pageSize.getWidth();
                const pdfHeight = (imgProps.height * pdfWidth) / imgProps.width;

                doc.addImage(imgData, 'PNG', 0, 0, pdfWidth, pdfHeight);
                doc.save("modelo_sumideros_completo.pdf");
            });
        }
        </script>
    </body>
    </html>
""", height=120)


#st.markdown("## 📘 Glosario de Modelo SNC")
with st.expander("📖 Términos clave del modelo", expanded=False):
    st.markdown("""
    **CAPEX**: Inversión de capital inicial en USD por hectárea. Se descuenta al inicio del proyecto.  
    **OPEX**: Costo operativo anual por hectárea (USD/año).  
    **Salvaguardas**: Porcentaje de reducción técnica del carbono proyectado por riesgos o incertidumbre.  
    **Ingreso por Encadenamiento**: Ingreso adicional constante por año (ej. agroindustria, turismo).  
    **Carbono Total**: Captura acumulada en toneladas de CO₂e durante la duración del proyecto.  
    **VPN**: Valor Presente Neto del flujo de caja (USD). Mide rentabilidad descontada al presente.  
    **Flujo de Caja Acumulado**: Evolución de ingresos menos costos netos año a año.
    **Otros Conceptos**: Nuevos Conceptos.            
    """)

# --- Exportar a Excel ---
import io
output = io.BytesIO()
with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
    df_resultados.to_excel(writer, index=False)
output.seek(0)

#st.markdown("##Exportar Resultados del Modelo")
st.download_button(
    label="Descargar Excel",
    data=output,
    file_name="resultados_modelo_SNC.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

# === PIE DE PÁGINA ===
st.markdown("""---""")
st.markdown("""
<div style='text-align: center; color: #888888; font-size: 12px;'>
    <p><strong>Sumideros Naturales de Carbono © 2025 (V3, 04.25) - Ger. Energías para la Transición </strong><br>
    Proyecto interno – Uso exclusivo para presentación ejecutiva</p>
</div>
""", unsafe_allow_html=True)

