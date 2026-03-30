import streamlit as st
import pandas as pd
from fpdf import FPDF
from datetime import datetime, date
import pytz
import unicodedata
import re
import io

# ── Configuración de la página ───────────────────────────────────
st.set_page_config(
    page_title="Registro Capital 100",
    page_icon="🏢",
    layout="wide"
)

# ── Constantes ───────────────────────────────────────────────────
SHEET_ID       = "1_Wn-YTbAC2kcRC6R_912NgnNQENUmnH-PGfgmVMoZ0g"
PRECIO_CONSULTA = 7600

# ── Funciones auxiliares ─────────────────────────────────────────
def url_hoja(nombre):
    return f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={nombre}"

def limpiar_moneda(valor):
    if pd.isna(valor) or str(valor).strip() == '':
        return 0.0
    try:
        return float(str(valor).strip().replace('$', '').replace(',', ''))
    except ValueError:
        return 0.0

def sanitizar_nombre(texto):
    sin_tildes = unicodedata.normalize('NFKD', str(texto)).encode('ascii', 'ignore').decode('ascii')
    return re.sub(r'[^\w\s-]', '', sin_tildes).strip().replace(' ', '_')

def pdf_a_bytes(pdf):
    """Convierte un objeto FPDF a bytes descargables."""
    output = pdf.output(dest='S')
    if isinstance(output, str):
        return output.encode('latin-1')
    return bytes(output)

def celda_componente(pdf, valor, estado, ancho):
    if estado == 'NO_APLICA':
        pdf.set_text_color(150, 150, 150)
        pdf.cell(ancho, 10, "No aplica", border=1, align='C')
    elif estado == 'PENDIENTE':
        pdf.set_text_color(220, 120, 0)
        pdf.cell(ancho, 10, "Pendiente", border=1, align='C')
    elif estado == 'YA_COBRADO':
        pdf.set_text_color(0, 128, 0)
        pdf.cell(ancho, 10, "Cobrado", border=1, align='C')
    else:
        pdf.set_text_color(0, 0, 0)
        pdf.cell(ancho, 10, f"$ {valor:,.2f}", border=1, align='R')
    pdf.set_text_color(0, 0, 0)

# ── Carga de datos ───────────────────────────────────────────────
@st.cache_data(ttl=300)  # cache de 5 minutos
def cargar_datos():
    try:
        df_tramites = pd.read_csv(url_hoja("TRAMITES"))
        df_pagos    = pd.read_csv(url_hoja("PAGOS"))
        df_gastos   = pd.read_csv(url_hoja("GASTOS"))
        df_caja     = pd.read_csv(url_hoja("CAJA"))
        df_sistema  = pd.read_csv(url_hoja("SISTEMA"))
    except Exception:
        st.error("❌ No se pudo acceder al Google Sheet. Verificá que sea público.")
        st.stop()

    for df in [df_tramites, df_pagos, df_gastos, df_caja, df_sistema]:
        df['FECHA'] = pd.to_datetime(df['FECHA'], dayfirst=True, errors='coerce')

    for col in ['INICIO DE CAJA', 'EFECTIVO', 'DEBITO', 'TRANSFERENCIA']:
        df_caja[col] = df_caja[col].apply(limpiar_moneda)

    df_total = df_tramites.copy()
    df_total['GESTORIA']      = df_total['GESTORIA'].astype(str).str.strip()
    df_total['TRAMITE']       = df_total['TRAMITE'].astype(str).str.strip()
    df_total['MEDIO DE PAGO'] = df_total['MEDIO DE PAGO'].fillna('').astype(str).str.strip().str.upper()

    cols_componentes = ['ARANCEL', 'SELLADO', 'ALTA/BAJA/INF.']
    for col in cols_componentes:
        if col in df_total.columns:
            def detectar_estado(v):
                if pd.isna(v): return 'PENDIENTE'
                s = str(v).strip().upper()
                if s == '': return 'PENDIENTE'
                if s == 'NO': return 'NO_APLICA'
                if s == 'COBRADO': return 'YA_COBRADO'
                return 'COBRADO'
            df_total[f'{col}_ESTADO'] = df_total[col].apply(detectar_estado)
            df_total[col] = df_total[col].apply(limpiar_moneda)

    for col in ['MONTO ABONADO', 'IMPORTE TOTAL']:
        if col in df_total.columns:
            df_total[col] = df_total[col].apply(limpiar_moneda)

    cols_sistema = ['ARANCELES SURA', 'FORMULARIOS SURA', 'PATENTES ARBA', 'PATENTES CABA']
    for col in cols_sistema:
        if col in df_sistema.columns:
            df_sistema[col] = df_sistema[col].apply(limpiar_moneda)

    df_total['DEBE'] = df_total.apply(
        lambda fila: fila['IMPORTE TOTAL'] - fila['MONTO ABONADO']
        if fila['GESTORIA'] == 'Particular'
        else fila['IMPORTE TOTAL'],
        axis=1
    )

    df_pagos['GESTORIA'] = df_pagos['GESTORIA'].astype(str).str.strip()
    df_pagos['MONTO']    = df_pagos['MONTO'].apply(limpiar_moneda)

    df_gastos['COSTO']         = df_gastos['COSTO'].apply(limpiar_moneda)
    df_gastos['MEDIO DE PAGO'] = df_gastos['MEDIO DE PAGO'].fillna('').astype(str).str.strip().str.upper()

    df_total = df_total.dropna(subset=['FECHA', 'GESTORIA'])

    return df_total, df_pagos, df_gastos, df_caja, df_sistema


# ── Generación PDF gestorías ─────────────────────────────────────
def generar_pdf_gestoria(nombre_gestoria, fecha, datos_grupo):
    pdf = FPDF()
    pdf.add_page()
    fecha_str = fecha.strftime('%d/%m/%Y')

    pdf.set_font("Arial", 'I', 10)
    pdf.cell(95, 10, f"Fecha: {fecha_str}", 0, 0, 'L')
    pdf.cell(95, 10, "Registro Capital 100", 0, 1, 'R')
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, f"Liquidación del día: {nombre_gestoria}", ln=True, align='C')
    pdf.ln(10)

    pdf.set_draw_color(0, 0, 0)
    pdf.set_fill_color(240, 240, 240)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", 'B', 8)

    tiene_ref = datos_grupo['REF'].apply(
        lambda v: pd.notna(v) and str(v).strip() not in ('', 'nan')
    ).any()

    if tiene_ref:
        columnas = ['TRAMITE', 'REF', 'N° / DOMINIO', 'ARANCEL', 'SELLADO', 'ALTA/BAJA', 'TOTAL']
        anchos   = [    25,     30,        30,            25,        25,         25,          30   ]
    else:
        columnas = ['TRAMITE', 'N° / DOMINIO', 'ARANCEL', 'SELLADO', 'ALTA/BAJA', 'TOTAL']
        anchos   = [    25,         35,           25,        25,         25,          55   ]

    for col, ancho in zip(columnas, anchos):
        pdf.cell(ancho, 10, col, border=1, align='C', fill=True)
    pdf.ln()

    pdf.set_font("Arial", size=8)
    for _, fila in datos_grupo.iterrows():
        pdf.set_text_color(0, 0, 0)
        pdf.cell(anchos[0], 10, str(fila['TRAMITE']), border=1)
        if tiene_ref:
            ref = str(fila['REF']) if pd.notna(fila.get('REF')) and str(fila.get('REF')).strip() not in ('', 'nan') else '-'
            pdf.cell(anchos[1], 10, ref, border=1)
            pdf.cell(anchos[2], 10, str(fila['N° RECIBO / DOMINIO']), border=1)
            celda_componente(pdf, fila['ARANCEL'],        fila['ARANCEL_ESTADO'],        anchos[3])
            celda_componente(pdf, fila['SELLADO'],        fila['SELLADO_ESTADO'],        anchos[4])
            celda_componente(pdf, fila['ALTA/BAJA/INF.'], fila['ALTA/BAJA/INF._ESTADO'], anchos[5])
            pdf.cell(anchos[6], 10, f"$ {fila['IMPORTE TOTAL']:,.2f}", border=1, align='R', ln=True)
        else:
            pdf.cell(anchos[1], 10, str(fila['N° RECIBO / DOMINIO']), border=1)
            celda_componente(pdf, fila['ARANCEL'],        fila['ARANCEL_ESTADO'],        anchos[2])
            celda_componente(pdf, fila['SELLADO'],        fila['SELLADO_ESTADO'],        anchos[3])
            celda_componente(pdf, fila['ALTA/BAJA/INF.'], fila['ALTA/BAJA/INF._ESTADO'], anchos[4])
            pdf.cell(anchos[5], 10, f"$ {fila['IMPORTE TOTAL']:,.2f}", border=1, align='R', ln=True)

        nota = str(fila['NOTA']) if pd.notna(fila.get('NOTA')) and str(fila.get('NOTA')).strip() not in ('', 'nan') else ''
        if nota:
            pdf.set_text_color(100, 100, 100)
            pdf.set_font("Arial", 'I', 7)
            pdf.cell(sum(anchos), 6, f"  Nota: {nota}", border=0, ln=True)
            pdf.set_font("Arial", size=8)

    pdf.set_text_color(0, 0, 0)
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 10)
    pdf.cell(0, 10, f"IMPORTE TOTAL DEL DÍA: $ {datos_grupo['IMPORTE TOTAL'].sum():,.2f}", border=0, align='R')
    pdf.ln(8)

    pdf.set_font("Arial", 'I', 8)
    pdf.set_text_color(130, 130, 130)
    pdf.multi_cell(0, 6,
        "* El monto indicado corresponde a los trámites realizados en el día. ",
        align='C'
    )

    return pdf_a_bytes(pdf)


# ── Cierre A ─────────────────────────────────────────────────────
def calcular_cierre(fecha, df_total, df_gastos, df_caja):
    datos_dia = df_total[df_total['FECHA'] == pd.Timestamp(fecha)]
    if datos_dia.empty:
        raise ValueError(f"No hay trámites registrados para {fecha.strftime('%d/%m/%Y')}.")

    particulares_dia = datos_dia[datos_dia['GESTORIA'] == 'Particular']
    sin_medio = particulares_dia[
        (particulares_dia['MONTO ABONADO'] > 0) &
        (particulares_dia['MEDIO DE PAGO'] == '')
    ]
    if not sin_medio.empty:
        detalle = sin_medio[['N° RECIBO / DOMINIO', 'MONTO ABONADO']].to_string(index=False)
        raise ValueError(
            f"Hay {len(sin_medio)} trámite(s) de particulares abonados sin medio de pago:\n{detalle}\n"
            f"Corregí la planilla antes de cerrar la caja."
        )

    medio = particulares_dia['MEDIO DE PAGO']
    esperado_efe = particulares_dia[medio == 'EFECTIVO'    ]['MONTO ABONADO'].sum()
    esperado_deb = particulares_dia[medio == 'DEBITO'      ]['MONTO ABONADO'].sum()
    esperado_tra = particulares_dia[medio == 'TRANSFERENCIA']['MONTO ABONADO'].sum()

    gestoria_dia   = datos_dia[datos_dia['GESTORIA'] != 'Particular']
    total_gestoria = gestoria_dia['IMPORTE TOTAL'].sum()

    gastos_dia = df_gastos[
        (df_gastos['FECHA'] == pd.Timestamp(fecha)) &
        (df_gastos['MEDIO DE PAGO'] == 'EFECTIVO')
    ]
    total_gastos_efe = gastos_dia['COSTO'].sum()

    teorico_efectivo = esperado_efe - total_gastos_efe
    teorico_digital  = esperado_deb + esperado_tra + total_gestoria

    caja_dia = df_caja[df_caja['FECHA'] == pd.Timestamp(fecha)]
    if caja_dia.empty:
        raise ValueError(f"No hay registro en CAJA para {fecha.strftime('%d/%m/%Y')}.")

    inicio_caja  = caja_dia['INICIO DE CAJA'].iloc[0]
    real_efe     = caja_dia['EFECTIVO'].iloc[0]
    real_digital = caja_dia['DEBITO'].iloc[0] + caja_dia['TRANSFERENCIA'].iloc[0]

    dif_efectivo  = (real_efe - inicio_caja) - teorico_efectivo
    dif_digital   = real_digital - teorico_digital
    balance_total = dif_efectivo + dif_digital

    return {
        'fecha'           : fecha.strftime('%d/%m/%Y'),
        'teorico_efectivo': teorico_efectivo,
        'teorico_digital' : teorico_digital,
        'inicio_caja'     : inicio_caja,
        'real_efe'        : real_efe,
        'real_digital'    : real_digital,
        'dif_efectivo'    : dif_efectivo,
        'dif_digital'     : dif_digital,
        'balance_total'   : balance_total,
        'gastos_dia'      : gastos_dia,
        'total_gastos_efe': total_gastos_efe,
        'gestoria_dia'    : gestoria_dia,
        'total_gestoria'  : total_gestoria,
    }


def generar_pdf_cierre(datos):
    pdf = FPDF()
    pdf.add_page()
    h = 10

    pdf.set_font("Arial", 'I', 10)
    pdf.cell(95, 10, f"Fecha: {datos['fecha']}", 0, 0, 'L')
    pdf.cell(95, 10, "Registro Capital 100", 0, 1, 'R')
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 15, f"Cierre de CAJA  {datos['fecha']}", ln=True, align='C')
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 8)
    pdf.set_fill_color(240, 240, 240)
    pdf.set_text_color(0, 0, 0)

    w_cat, w_bal = 50, 75
    x_start = (210 - (w_cat * 2 + w_bal)) / 2

    pdf.set_x(x_start)
    for titulo, ancho in [("ESPERADO", w_cat), ("REAL", w_cat), ("BALANCE", w_bal)]:
        pdf.cell(ancho, h, titulo, border=1, align='C', fill=True)
    pdf.ln()

    pdf.set_x(x_start)
    sub_anchos = [w_cat/2, w_cat/2, w_cat/2, w_cat/2, w_bal/3, w_bal/3, w_bal/3]
    sub_labels = ['VIRTUAL', 'EFECTIVO', 'VIRTUAL', 'EFECTIVO', 'VIRTUAL', 'EFECTIVO', 'TOTAL']
    for label, ancho in zip(sub_labels, sub_anchos):
        pdf.cell(ancho, h, label, border=1, align='C', fill=True)
    pdf.ln()

    pdf.set_x(x_start)
    pdf.set_font("Arial", size=9)
    valores = [
        datos['teorico_digital'], datos['teorico_efectivo'],
        datos['real_digital'],    datos['real_efe'],
        datos['dif_digital'],     datos['dif_efectivo'],
    ]
    for valor, ancho in zip(valores, sub_anchos[:-1]):
        pdf.cell(ancho, h, f"$ {valor:,.2f}", border=1, align='C')
    pdf.set_font("Arial", 'B', 9)
    pdf.cell(sub_anchos[-1], h, f"$ {datos['balance_total']:,.2f}", border=1, align='C')
    pdf.ln(15)

    pdf.set_font("Arial", 'I', 8)
    pdf.set_text_color(130, 130, 130)
    pdf.set_x(x_start)
    pdf.cell(0, 6, f"* Inicio de caja descontado: $ {datos['inicio_caja']:,.2f}", ln=True)
    pdf.ln(2)

    if not datos['gestoria_dia'].empty:
        gestoras_del_dia = datos['gestoria_dia']['GESTORIA'].unique()
        nombres = ', '.join(sorted(gestoras_del_dia))
        pdf.set_font("Arial", 'I', 8)
        pdf.set_text_color(130, 130, 130)
        pdf.multi_cell(0, 6,
            f"* Se consideraron como ya abonados los trámites del día de las siguientes "
            f"gestorías: {nombres}. Monto total: $ {datos['total_gestoria']:,.2f}.",
            align='C'
        )
        pdf.ln(4)

    if not datos['gastos_dia'].empty:
        pdf.set_font("Arial", 'B', 10)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, "Gastos del día (efectivo)", ln=True)
        pdf.set_font("Arial", 'B', 8)
        pdf.set_fill_color(240, 240, 240)
        for col, ancho in [("MOTIVO", 120), ("COSTO", 70)]:
            pdf.cell(ancho, h, col, border=1, align='C', fill=True)
        pdf.ln()
        pdf.set_font("Arial", size=8)
        for _, gasto in datos['gastos_dia'].iterrows():
            pdf.set_text_color(0, 0, 0)
            pdf.cell(120, h, str(gasto['MOTIVO']), border=1)
            pdf.cell(70,  h, f"$ {gasto['COSTO']:,.2f}", border=1, align='R')
            pdf.ln()
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(120, h, "TOTAL GASTOS", border=1, align='R')
        pdf.cell(70,  h, f"$ {datos['total_gastos_efe']:,.2f}", border=1, align='R')
        pdf.ln(10)

    pdf.set_font("Arial", 'B', 11)
    pdf.set_text_color(0, 0, 0)
    bt, bv, be = datos['balance_total'], datos['dif_digital'], datos['dif_efectivo']
    if bt == 0 and bv == 0 and be == 0:
        pdf.set_text_color(0, 128, 0)
        mensaje = "La caja cerró correctamente."
    elif bt == 0:
        pdf.set_text_color(0, 0, 255)
        mensaje = "La caja total cerró bien. Revisar asignación de medio de pago."
    else:
        pdf.set_text_color(255, 0, 0)
        mensaje = f"La caja no cerró. Diferencia: $ {bt:,.2f}"
    pdf.multi_cell(0, 10, mensaje, align='C')

    return pdf_a_bytes(pdf)


# ── Cierre B ─────────────────────────────────────────────────────
def procesar_suats(archivo, fecha):
    nombre = archivo.name.lower()
    if 'sellos' in nombre:
        tipo = 'SUATS Sellos'
    elif 'patentes' in nombre:
        tipo = 'SUATS Patentes'
    elif 'infracciones' in nombre:
        tipo = 'SUATS Infracciones'
    else:
        raise ValueError(f"No se reconoce el tipo de archivo: {archivo.name}")

    df = pd.read_excel(archivo)
    df.columns = [c.strip() for c in df.columns]
    df['Fecha Consulta'] = pd.to_datetime(df['Fecha Consulta'], errors='coerce')
    df['Fecha Acción']   = pd.to_datetime(df['Fecha Acción'],   errors='coerce')
    df['Monto']          = df['Monto'].apply(limpiar_moneda)

    consultas_dia = df[df['Fecha Consulta'].dt.date == fecha]
    pagos_dia     = df[
        (df['Fecha Acción'].dt.date == fecha) &
        (df['Acción'].str.strip() == 'Comprobante de Pago')
    ]

    n_consultas   = len(consultas_dia)
    monto_consult = n_consultas * PRECIO_CONSULTA
    monto_pagos   = pagos_dia['Monto'].sum()

    return {
        'tipo'         : tipo,
        'n_consultas'  : n_consultas,
        'monto_consult': monto_consult,
        'monto_pagos'  : monto_pagos,
        'total'        : monto_consult + monto_pagos,
    }


def calcular_cierre_B(fecha, archivos_suats, df_caja, df_sistema):
    resultados_suats = []
    for archivo in archivos_suats:
        resultado = procesar_suats(archivo, fecha)
        resultados_suats.append(resultado)

    total_suats = sum(r['total'] for r in resultados_suats)

    sistema_dia = df_sistema[df_sistema['FECHA'] == pd.Timestamp(fecha)]
    if sistema_dia.empty:
        raise ValueError(f"No hay datos en SISTEMA para {fecha.strftime('%d/%m/%Y')}. Completá la planilla.")

    aranceles_sura   = sistema_dia['ARANCELES SURA'].iloc[0]
    formularios_sura = sistema_dia['FORMULARIOS SURA'].iloc[0]
    patentes_arba    = sistema_dia['PATENTES ARBA'].iloc[0]
    patentes_caba    = sistema_dia['PATENTES CABA'].iloc[0]
    total_manual     = aranceles_sura + formularios_sura + patentes_arba + patentes_caba

    caja_dia = df_caja[df_caja['FECHA'] == pd.Timestamp(fecha)]
    if caja_dia.empty:
        raise ValueError(f"No hay registro en CAJA para {fecha.strftime('%d/%m/%Y')}.")

    inicio_caja   = caja_dia['INICIO DE CAJA'].iloc[0]
    efectivo      = caja_dia['EFECTIVO'].iloc[0]
    debito        = caja_dia['DEBITO'].iloc[0]
    transferencia = caja_dia['TRANSFERENCIA'].iloc[0]

    total_ingresos = inicio_caja + total_suats + total_manual
    total_egresos  = efectivo + debito + transferencia

    return {
        'fecha'           : fecha.strftime('%d/%m/%Y'),
        'resultados_suats': resultados_suats,
        'total_suats'     : total_suats,
        'aranceles_sura'  : aranceles_sura,
        'formularios_sura': formularios_sura,
        'patentes_arba'   : patentes_arba,
        'patentes_caba'   : patentes_caba,
        'total_manual'    : total_manual,
        'inicio_caja'     : inicio_caja,
        'total_ingresos'  : total_ingresos,
        'efectivo'        : efectivo,
        'debito'          : debito,
        'transferencia'   : transferencia,
        'total_egresos'   : total_egresos,
        'resultado'       : total_ingresos - total_egresos,
    }


def generar_pdf_cierre_B(datos):
    pdf = FPDF()
    pdf.add_page()
    h = 10

    pdf.set_font("Arial", 'I', 10)
    pdf.cell(95, 10, f"Fecha: {datos['fecha']}", 0, 0, 'L')
    pdf.cell(95, 10, "Registro Capital 100", 0, 1, 'R')
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 16)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 15, f"Cierre de Caja — Verificación Sistema   {datos['fecha']}", ln=True, align='C')
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 9)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(0, h, "INGRESOS DEL SISTEMA", ln=True)
    pdf.ln(2)

    anchos = [70, 35, 40, 45]
    for col, ancho in zip(['FUENTE', 'CONSULTAS', 'PAGOS', 'TOTAL'], anchos):
        pdf.cell(ancho, h, col, border=1, align='C', fill=True)
    pdf.ln()

    pdf.set_font("Arial", size=8)
    for r in datos['resultados_suats']:
        pdf.set_text_color(0, 0, 0)
        pdf.cell(anchos[0], h, r['tipo'],                       border=1)
        pdf.cell(anchos[1], h, f"$ {r['monto_consult']:,.2f}", border=1, align='R')
        pdf.cell(anchos[2], h, f"$ {r['monto_pagos']:,.2f}",   border=1, align='R')
        pdf.cell(anchos[3], h, f"$ {r['total']:,.2f}",          border=1, align='R', ln=True)

    for nombre_item, monto in [
        ('Aranceles SURA (manual)',   datos['aranceles_sura']),
        ('Formularios SURA (manual)', datos['formularios_sura']),
        ('Patentes ARBA (manual)',    datos['patentes_arba']),
        ('Patentes CABA (manual)',    datos['patentes_caba']),
        ('Inicio de caja',            datos['inicio_caja']),
    ]:
        pdf.set_text_color(100, 100, 100)
        pdf.cell(anchos[0], h, nombre_item, border=1)
        pdf.cell(anchos[1], h, "—",         border=1, align='C')
        pdf.cell(anchos[2], h, "—",         border=1, align='C')
        pdf.cell(anchos[3], h, f"$ {monto:,.2f}", border=1, align='R', ln=True)

    pdf.set_font("Arial", 'B', 9)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(sum(anchos[:3]), h, "TOTAL INGRESOS", border=1, align='R')
    pdf.cell(anchos[3], h, f"$ {datos['total_ingresos']:,.2f}", border=1, align='R')
    pdf.ln(8)

    pdf.set_font("Arial", 'B', 9)
    pdf.cell(0, h, "EGRESOS DECLARADOS", ln=True)
    pdf.ln(2)

    anchos_e = [110, 80]
    for col, ancho in zip(['CONCEPTO', 'MONTO'], anchos_e):
        pdf.cell(ancho, h, col, border=1, align='C', fill=True)
    pdf.ln()

    pdf.set_font("Arial", size=8)
    for concepto, monto in [
        ("Débito (postnet)", datos['debito']),
        ("Efectivo contado", datos['efectivo']),
        ("Transferencias",   datos['transferencia']),
    ]:
        pdf.set_text_color(0, 0, 0)
        pdf.cell(anchos_e[0], h, concepto,           border=1)
        pdf.cell(anchos_e[1], h, f"$ {monto:,.2f}", border=1, align='R', ln=True)

    pdf.set_font("Arial", 'B', 9)
    pdf.cell(anchos_e[0], h, "TOTAL EGRESOS", border=1, align='R')
    pdf.cell(anchos_e[1], h, f"$ {datos['total_egresos']:,.2f}", border=1, align='R')
    pdf.ln(10)

    pdf.set_font("Arial", 'B', 12)
    resultado = datos['resultado']
    if resultado == 0:
        pdf.set_text_color(0, 128, 0)
        mensaje = "La caja cerró correctamente según el sistema."
    elif resultado > 0:
        pdf.set_text_color(0, 0, 255)
        mensaje = f"El sistema registra un excedente de $ {resultado:,.2f}"
    else:
        pdf.set_text_color(255, 0, 0)
        mensaje = f"El sistema registra un faltante de $ {abs(resultado):,.2f}"
    pdf.multi_cell(0, 10, mensaje, align='C')

    return pdf_a_bytes(pdf)


# ── Deudas ───────────────────────────────────────────────────────
def calcular_deudas(df_total, df_pagos):
    deudas = {}

    gestoria_total = df_total[df_total['GESTORIA'] != 'Particular']
    for gestoria, grupo in gestoria_total.groupby('GESTORIA'):
        importe_total  = grupo['IMPORTE TOTAL'].sum()
        pagos_gestoria = df_pagos[df_pagos['GESTORIA'] == gestoria]['MONTO'].sum()
        deuda_neta     = importe_total - pagos_gestoria

        if deuda_neta > 0:
            deudas[gestoria] = {
                'tipo'         : 'GESTORIA',
                'total'        : deuda_neta,
                'importe_total': importe_total,
                'pagos'        : pagos_gestoria,
                'detalle'      : grupo[['FECHA', 'TRAMITE', 'REF', 'N° RECIBO / DOMINIO',
                                        'IMPORTE TOTAL']].sort_values('FECHA'),
                'detalle_pagos': df_pagos[df_pagos['GESTORIA'] == gestoria][
                                    ['FECHA', 'MONTO']].sort_values('FECHA'),
            }

    particulares = df_total[(df_total['GESTORIA'] == 'Particular') & (df_total['DEBE'] > 0)]
    if not particulares.empty:
        deudas['Particular'] = {
            'tipo'   : 'PARTICULAR',
            'total'  : particulares['DEBE'].sum(),
            'detalle': particulares[['FECHA', 'TRAMITE', 'REF', 'N° RECIBO / DOMINIO',
                                     'IMPORTE TOTAL', 'DEBE']].sort_values('FECHA'),
        }

    return deudas


def generar_pdf_deudas(deudas):
    hoy = datetime.now(pytz.timezone('America/Argentina/Buenos_Aires'))
    pdf = FPDF()

    for nombre, datos in sorted(deudas.items(), key=lambda x: -x[1]['total']):
        pdf.add_page()
        pdf.set_text_color(0, 0, 0)

        pdf.set_font("Arial", 'I', 10)
        pdf.cell(95, 10, f"Emitido: {hoy.strftime('%d/%m/%Y')}", 0, 0, 'L')
        pdf.cell(95, 10, "Registro Capital 100", 0, 1, 'R')
        pdf.ln(5)

        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, f"Estado de cuenta: {nombre}", ln=True, align='C')
        pdf.ln(8)

        if datos['tipo'] == 'GESTORIA':
            tiene_ref = datos['detalle']['REF'].apply(
                lambda v: pd.notna(v) and str(v).strip() not in ('', 'nan')
            ).any()

            pdf.set_font("Arial", 'B', 9)
            pdf.cell(0, 8, "Trámites realizados:", ln=True)
            pdf.set_font("Arial", 'B', 8)
            pdf.set_fill_color(240, 240, 240)

            if tiene_ref:
                columnas = ['FECHA', 'TRAMITE', 'REF', 'N° / DOMINIO', 'IMPORTE TOTAL']
                anchos   = [  25,      35,        30,        30,               70        ]
            else:
                columnas = ['FECHA', 'TRAMITE', 'N° / DOMINIO', 'IMPORTE TOTAL']
                anchos   = [  25,      40,           40,               85        ]

            for col, ancho in zip(columnas, anchos):
                pdf.cell(ancho, 10, col, border=1, align='C', fill=True)
            pdf.ln()

            pdf.set_font("Arial", size=8)
            for _, fila in datos['detalle'].iterrows():
                pdf.set_text_color(0, 0, 0)
                pdf.cell(anchos[0], 10, fila['FECHA'].strftime('%d/%m/%Y'), border=1, align='C')
                pdf.cell(anchos[1], 10, str(fila['TRAMITE']),               border=1)
                if tiene_ref:
                    ref = str(fila['REF']) if pd.notna(fila.get('REF')) and str(fila.get('REF')).strip() not in ('', 'nan') else '-'
                    pdf.cell(anchos[2], 10, ref,                                border=1)
                    pdf.cell(anchos[3], 10, str(fila['N° RECIBO / DOMINIO']),   border=1)
                    pdf.cell(anchos[4], 10, f"$ {fila['IMPORTE TOTAL']:,.2f}",  border=1, align='R', ln=True)
                else:
                    pdf.cell(anchos[2], 10, str(fila['N° RECIBO / DOMINIO']),   border=1)
                    pdf.cell(anchos[3], 10, f"$ {fila['IMPORTE TOTAL']:,.2f}",  border=1, align='R', ln=True)

            espaciador = sum(anchos[:-1])
            pdf.set_font("Arial", 'B', 9)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(espaciador, 10, "TOTAL TRÁMITES", border=1, align='R')
            pdf.cell(anchos[-1], 10, f"$ {datos['importe_total']:,.2f}", border=1, align='R')
            pdf.ln(10)

            if not datos['detalle_pagos'].empty:
                pdf.set_font("Arial", 'B', 9)
                pdf.set_text_color(0, 0, 0)
                pdf.cell(0, 8, "Pagos registrados:", ln=True)
                pdf.set_font("Arial", 'B', 8)
                pdf.set_fill_color(240, 240, 240)
                for col, ancho in [('FECHA', 25), ('MONTO', 165)]:
                    pdf.cell(ancho, 10, col, border=1, align='C', fill=True)
                pdf.ln()
                pdf.set_font("Arial", size=8)
                for _, pago in datos['detalle_pagos'].iterrows():
                    pdf.set_text_color(0, 0, 0)
                    pdf.cell(25,  10, pago['FECHA'].strftime('%d/%m/%Y'), border=1, align='C')
                    pdf.set_text_color(0, 128, 0)
                    pdf.cell(165, 10, f"$ {pago['MONTO']:,.2f}", border=1, align='R', ln=True)
                pdf.set_font("Arial", 'B', 9)
                pdf.set_text_color(0, 128, 0)
                pdf.cell(25,  10, "TOTAL PAGADO", border=1, align='R')
                pdf.cell(165, 10, f"$ {datos['pagos']:,.2f}", border=1, align='R')
                pdf.ln(10)

            pdf.set_font("Arial", 'B', 11)
            pdf.set_text_color(200, 0, 0)
            pdf.cell(espaciador, 10, "DEUDA NETA:", border=1, align='R')
            pdf.cell(anchos[-1], 10, f"$ {datos['total']:,.2f}", border=1, align='R')

        elif datos['tipo'] == 'PARTICULAR':
            tiene_ref = datos['detalle']['REF'].apply(
                lambda v: pd.notna(v) and str(v).strip() not in ('', 'nan')
            ).any()

            pdf.set_font("Arial", 'B', 8)
            pdf.set_fill_color(240, 240, 240)

            if tiene_ref:
                columnas = ['FECHA', 'TRAMITE', 'REF', 'N° / DOMINIO', 'IMPORTE TOTAL', 'DEBE']
                anchos   = [  25,      30,        25,        25,               45,          40  ]
            else:
                columnas = ['FECHA', 'TRAMITE', 'N° / DOMINIO', 'IMPORTE TOTAL', 'DEBE']
                anchos   = [  25,      35,           35,               45,          50  ]

            for col, ancho in zip(columnas, anchos):
                pdf.cell(ancho, 10, col, border=1, align='C', fill=True)
            pdf.ln()

            pdf.set_font("Arial", size=8)
            for _, fila in datos['detalle'].iterrows():
                pdf.set_text_color(0, 0, 0)
                pdf.cell(anchos[0], 10, fila['FECHA'].strftime('%d/%m/%Y'), border=1, align='C')
                pdf.cell(anchos[1], 10, str(fila['TRAMITE']),               border=1)
                if tiene_ref:
                    ref = str(fila['REF']) if pd.notna(fila.get('REF')) and str(fila.get('REF')).strip() not in ('', 'nan') else '-'
                    pdf.cell(anchos[2], 10, ref,                                    border=1)
                    pdf.cell(anchos[3], 10, str(fila['N° RECIBO / DOMINIO']),       border=1)
                    pdf.cell(anchos[4], 10, f"$ {fila['IMPORTE TOTAL']:,.2f}",      border=1, align='R')
                    pdf.set_text_color(200, 0, 0)
                    pdf.cell(anchos[5], 10, f"$ {fila['DEBE']:,.2f}",               border=1, align='R', ln=True)
                else:
                    pdf.cell(anchos[2], 10, str(fila['N° RECIBO / DOMINIO']),       border=1)
                    pdf.cell(anchos[3], 10, f"$ {fila['IMPORTE TOTAL']:,.2f}",      border=1, align='R')
                    pdf.set_text_color(200, 0, 0)
                    pdf.cell(anchos[4], 10, f"$ {fila['DEBE']:,.2f}",               border=1, align='R', ln=True)

            pdf.set_font("Arial", 'B', 10)
            pdf.set_text_color(0, 0, 0)
            espaciador = sum(anchos[:-2])
            pdf.cell(espaciador, 10, "", 0)
            pdf.set_text_color(200, 0, 0)
            pdf.cell(anchos[-2], 10, "TOTAL ADEUDADO:", 0, 0, 'R')
            pdf.cell(anchos[-1], 10, f"$ {datos['total']:,.2f}", border=1, align='R')

    return pdf_a_bytes(pdf)


# ══════════════════════════════════════════════════════════════════
# INTERFAZ STREAMLIT
# ══════════════════════════════════════════════════════════════════

st.title("🏢 Registro Capital 100")
st.caption("Sistema de cierre de caja")

# ── Autenticación ────────────────────────────────────────────────
password = st.text_input("Contraseña:", type="password")
if password != st.secrets["PASSWORD"]:
    st.warning("Ingresá la contraseña para continuar.")
    st.stop()

# Sidebar
with st.sidebar:
    st.header("Menú")
    seccion = st.radio(
        "Seleccioná una sección:",
        ["📄 PDF Gestorías", "🧾 Cierre de Caja", "💰 Estado de Deudas"],
        label_visibility="collapsed"
    )
    st.divider()
    if st.button("🔄 Actualizar datos"):
        st.cache_data.clear()
        st.rerun()
    st.caption("Los datos se actualizan automáticamente cada 5 minutos.")
    st.divider()
    st.markdown(f"[📊 Abrir Google Sheets](https://docs.google.com/spreadsheets/d/{SHEET_ID})")

# Cargamos datos
with st.spinner("Cargando datos desde Google Sheets..."):
    df_total, df_pagos, df_gastos, df_caja, df_sistema = cargar_datos()

st.success(f"✅ Datos cargados — {len(df_total)} trámites registrados.")
st.divider()


# ── Sección 1: PDF Gestorías ─────────────────────────────────────
if seccion == "📄 PDF Gestorías":
    st.header("📄 PDF de Gestorías")
    st.write("Generá el reporte de liquidación del día para cada gestoría.")

    fecha = st.date_input("Seleccioná la fecha:", value=date.today(), format="DD/MM/YYYY")

    if st.button("Generar PDFs", type="primary"):
        fecha_ts = pd.Timestamp(fecha)
        datos_dia = df_total[df_total['FECHA'] == fecha_ts]
        gestoras  = datos_dia[datos_dia['GESTORIA'] != 'Particular']['GESTORIA'].unique()

        if len(gestoras) == 0:
            st.warning(f"No hay trámites de gestorías para el {fecha.strftime('%d/%m/%Y')}.")
        else:
            for gestoria in sorted(gestoras):
                datos_grupo = datos_dia[datos_dia['GESTORIA'] == gestoria]
                try:
                    pdf_bytes = generar_pdf_gestoria(gestoria, fecha_ts, datos_grupo)
                    nombre    = f"Reporte_{sanitizar_nombre(gestoria)}_{fecha.strftime('%d-%m-%Y')}.pdf"
                    st.download_button(
                        label=f"⬇️ Descargar — {gestoria}",
                        data=pdf_bytes,
                        file_name=nombre,
                        mime="application/pdf",
                        key=f"pdf_{gestoria}"
                    )
                    st.success(f"✅ {nombre}")
                except Exception as ex:
                    st.error(f"❌ Error en {gestoria}: {ex}")
        

# ── Sección 2: Cierre de Caja (A y B) ───────────────────────────
elif seccion == "🧾 Cierre de Caja":
    st.header("🧾 Cierre de Caja")

    tipo_cierre = st.radio(
        "Seleccioná el tipo de cierre:",
        ["Cierre A — Verificación interna", "Cierre B — Verificación sistema"],
        horizontal=True
    )
    st.divider()

    if tipo_cierre == "Cierre A — Verificación interna":
        st.write("Contrasta los trámites anotados con el dinero en caja.")

        fecha = st.date_input("Seleccioná la fecha:", value=date.today(), format="DD/MM/YYYY")

        if st.button("Generar Cierre de Caja", type="primary"):
            try:
                datos     = calcular_cierre(fecha, df_total, df_gastos, df_caja)
                pdf_bytes = generar_pdf_cierre(datos)
                nombre    = f"Cierre_Caja_{fecha.strftime('%d-%m-%Y')}.pdf"

                col1, col2, col3 = st.columns(3)
                col1.metric("Balance total",       f"$ {datos['balance_total']:,.2f}")
                col2.metric("Diferencia efectivo", f"$ {datos['dif_efectivo']:,.2f}")
                col3.metric("Diferencia digital",  f"$ {datos['dif_digital']:,.2f}")

                if datos['balance_total'] == 0:
                    st.success("✅ La caja cerró correctamente.")
                else:
                    st.error(f"❌ La caja no cerró. Diferencia: $ {datos['balance_total']:,.2f}")

                if not datos['gestoria_dia'].empty:
                    nombres = ', '.join(sorted(datos['gestoria_dia']['GESTORIA'].unique()))
                    st.info(f"📋 Gestorías consideradas como pagas: {nombres}")

                st.download_button(
                    label="⬇️ Descargar PDF",
                    data=pdf_bytes,
                    file_name=nombre,
                    mime="application/pdf"
                )
            except ValueError as ex:
                st.warning(f"⚠️ {ex}")
            except Exception as ex:
                st.error(f"❌ Error inesperado: {ex}")

    else:
        st.write("Contrasta los datos de los sistemas oficiales con la caja.")

        fecha = st.date_input("Seleccioná la fecha:", value=date.today(), format="DD/MM/YYYY")

        st.subheader("Archivos SUATS")
        archivos_suats = st.file_uploader(
            "Subí los tres archivos xlsx (sellos, patentes, infracciones):",
            type="xlsx",
            accept_multiple_files=True
        )

        if archivos_suats:
            tipos_detectados = []
            for a in archivos_suats:
                n = a.name.lower()
                if 'sellos' in n:
                    tipos_detectados.append(f"✅ Sellos — `{a.name}`")
                elif 'patentes' in n:
                    tipos_detectados.append(f"✅ Patentes — `{a.name}`")
                elif 'infracciones' in n:
                    tipos_detectados.append(f"✅ Infracciones — `{a.name}`")
                else:
                    tipos_detectados.append(f"⚠️ No reconocido — `{a.name}`")
            for t in tipos_detectados:
                st.write(t)

        if st.button("Generar Cierre Sistema", type="primary"):
            if not archivos_suats:
                st.warning("⚠️ Subí al menos un archivo SUATS antes de continuar.")
            else:
                try:
                    datos     = calcular_cierre_B(fecha, archivos_suats, df_caja, df_sistema)
                    pdf_bytes = generar_pdf_cierre_B(datos)
                    nombre    = f"CierreB_{fecha.strftime('%d-%m-%Y')}.pdf"

                    col1, col2, col3 = st.columns(3)
                    col1.metric("Total ingresos sistema", f"$ {datos['total_ingresos']:,.2f}")
                    col2.metric("Total egresos",           f"$ {datos['total_egresos']:,.2f}")
                    col3.metric("Resultado",               f"$ {datos['resultado']:,.2f}")

                    resultado = datos['resultado']
                    if resultado == 0:
                        st.success("✅ La caja cerró correctamente según el sistema.")
                    elif resultado > 0:
                        st.info(f"ℹ️ El sistema registra un excedente de $ {resultado:,.2f}")
                    else:
                        st.error(f"❌ El sistema registra un faltante de $ {abs(resultado):,.2f}")

                    st.download_button(
                        label="⬇️ Descargar PDF",
                        data=pdf_bytes,
                        file_name=nombre,
                        mime="application/pdf"
                    )
                except ValueError as ex:
                    st.warning(f"⚠️ {ex}")
                except Exception as ex:
                    st.error(f"❌ Error inesperado: {ex}")


# ── Sección 3: Deudas ────────────────────────────────────────────
elif seccion == "💰 Estado de Deudas":
    st.header("💰 Estado de Deudas")
    st.write("Resumen de deudas acumuladas por gestoría y particulares.")

    deudas = calcular_deudas(df_total, df_pagos)

    if not deudas:
        st.success("✅ No hay deudas pendientes.")
    else:
        total_general = sum(d['total'] for d in deudas.values())
        st.metric("Total general adeudado", f"$ {total_general:,.2f}")
        st.divider()

        for nombre, datos in sorted(deudas.items(), key=lambda x: -x[1]['total']):
            with st.expander(f"📋 {nombre} — $ {datos['total']:,.2f}"):
                if datos['tipo'] == 'GESTORIA':
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Trámites",   f"$ {datos['importe_total']:,.2f}")
                    col2.metric("Pagado",     f"$ {datos['pagos']:,.2f}")
                    col3.metric("Deuda neta", f"$ {datos['total']:,.2f}")
                    st.dataframe(datos['detalle'], use_container_width=True, hide_index=True)
                    if not datos['detalle_pagos'].empty:
                        st.write("**Pagos registrados:**")
                        st.dataframe(datos['detalle_pagos'], use_container_width=True, hide_index=True)
                else:
                    st.metric("Total adeudado", f"$ {datos['total']:,.2f}")
                    st.dataframe(datos['detalle'], use_container_width=True, hide_index=True)

        st.divider()
        hoy = datetime.now(pytz.timezone('America/Argentina/Buenos_Aires'))
        if st.button("Generar PDF de Deudas", type="primary"):
            try:
                pdf_bytes = generar_pdf_deudas(deudas)
                nombre    = f"Deudas_{hoy.strftime('%d-%m-%Y')}.pdf"
                st.download_button(
                    label="⬇️ Descargar PDF",
                    data=pdf_bytes,
                    file_name=nombre,
                    mime="application/pdf"
                )
            except Exception as ex:
                st.error(f"❌ Error al generar PDF: {ex}")
