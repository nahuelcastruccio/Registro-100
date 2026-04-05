import streamlit as st
import pandas as pd
from fpdf import FPDF
from datetime import datetime, date
import pytz
import unicodedata
import re
import io
import pdfplumber
import anthropic

# ── Configuración de la página ───────────────────────────────────
st.set_page_config(
    page_title="Registro Capital 100",
    page_icon="🏢",
    layout="wide"
)

SHEET_ID        = "1_Wn-YTbAC2kcRC6R_912NgnNQENUmnH-PGfgmVMoZ0g"
PRECIO_CONSULTA = 7600

# ══════════════════════════════════════════════════════════════════
# FUNCIONES AUXILIARES
# ══════════════════════════════════════════════════════════════════

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

# ══════════════════════════════════════════════════════════════════
# CARGA DE DATOS
# ══════════════════════════════════════════════════════════════════

@st.cache_data(ttl=300)
def cargar_datos():
    try:
        df_tramites        = pd.read_csv(url_hoja("TRAMITES"))
        df_pagos           = pd.read_csv(url_hoja("PAGOS"))
        df_gastos          = pd.read_csv(url_hoja("GASTOS"))
        df_caja            = pd.read_csv(url_hoja("CAJA"))
        df_sistema         = pd.read_csv(url_hoja("SISTEMA"))
        df_gestorías_banco = pd.read_csv(url_hoja("GESTORÍAS_BANCO"))
    except Exception:
        st.error("No se pudo acceder al Google Sheet. Verificá que sea público.")
        st.stop()

    for df in [df_tramites, df_pagos, df_gastos, df_caja, df_sistema]:
        df['FECHA'] = pd.to_datetime(df['FECHA'], dayfirst=True, errors='coerce')

    for col in ['INICIO DE CAJA', 'EFECTIVO', 'DEBITO']:
        df_caja[col] = df_caja[col].apply(limpiar_moneda)

    df_total = df_tramites.copy()
    df_total['GESTORIA']      = df_total['GESTORIA'].astype(str).str.strip()
    df_total['TRAMITE']       = df_total['TRAMITE'].astype(str).str.strip()
    df_total['MEDIO DE PAGO'] = df_total['MEDIO DE PAGO'].fillna('').astype(str).str.strip().str.upper()

    for col in ['ARANCEL', 'SELLADO', 'ALTA/BAJA/INF.']:
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

    for col in ['PATENTES ARBA', 'PATENTES CABA']:
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
    df_gastos['COSTO']   = df_gastos['COSTO'].apply(limpiar_moneda)
    df_gastos['MEDIO DE PAGO'] = df_gastos['MEDIO DE PAGO'].fillna('').astype(str).str.strip().str.upper()
    df_gestorías_banco['ALIAS_BANCO'] = df_gestorías_banco['ALIAS_BANCO'].astype(str).str.strip()

    df_total = df_total.dropna(subset=['FECHA', 'GESTORIA'])
    return df_total, df_pagos, df_gastos, df_caja, df_sistema, df_gestorías_banco

# ══════════════════════════════════════════════════════════════════
# PDF GESTORÍAS
# ══════════════════════════════════════════════════════════════════

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
        anchos   = [25, 30, 30, 25, 25, 25, 30]
    else:
        columnas = ['TRAMITE', 'N° / DOMINIO', 'ARANCEL', 'SELLADO', 'ALTA/BAJA', 'TOTAL']
        anchos   = [25, 35, 25, 25, 25, 55]

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
        "* El monto indicado corresponde a los trámites realizados en el día. "
        "El pago puede realizarse en el día o al día siguiente.", align='C')
    return pdf_a_bytes(pdf)

# ══════════════════════════════════════════════════════════════════
# CIERRE A
# ══════════════════════════════════════════════════════════════════

def calcular_cierre_A(fecha, df_total, df_gastos, df_caja):
    datos_dia = df_total[df_total['FECHA'] == pd.Timestamp(fecha)]
    if datos_dia.empty:
        raise ValueError(f"No hay trámites registrados para {fecha.strftime('%d/%m/%Y')}.")

    particulares_dia = datos_dia[datos_dia['GESTORIA'] == 'Particular']
    sin_medio = particulares_dia[(particulares_dia['MONTO ABONADO'] > 0) & (particulares_dia['MEDIO DE PAGO'] == '')]
    if not sin_medio.empty:
        detalle = sin_medio[['N° RECIBO / DOMINIO', 'MONTO ABONADO']].to_string(index=False)
        raise ValueError(f"Hay {len(sin_medio)} trámite(s) sin medio de pago:\n{detalle}\nCorregí la planilla.")

    medio        = particulares_dia['MEDIO DE PAGO']
    esperado_efe = particulares_dia[medio == 'EFECTIVO'    ]['MONTO ABONADO'].sum()
    esperado_deb = particulares_dia[medio == 'DEBITO'      ]['MONTO ABONADO'].sum()
    esperado_tra = particulares_dia[medio == 'TRANSFERENCIA']['MONTO ABONADO'].sum()

    gestoria_dia   = datos_dia[datos_dia['GESTORIA'] != 'Particular']
    total_gestoria = gestoria_dia['IMPORTE TOTAL'].sum()

    gastos_dia = df_gastos[(df_gastos['FECHA'] == pd.Timestamp(fecha)) & (df_gastos['MEDIO DE PAGO'] == 'EFECTIVO')]
    total_gastos_efe = gastos_dia['COSTO'].sum()

    teorico_efectivo = esperado_efe - total_gastos_efe
    teorico_digital  = esperado_deb + esperado_tra + total_gestoria

    caja_dia = df_caja[df_caja['FECHA'] == pd.Timestamp(fecha)]
    if caja_dia.empty:
        raise ValueError(f"No hay registro en CAJA para {fecha.strftime('%d/%m/%Y')}.")

    inicio_caja  = caja_dia['INICIO DE CAJA'].iloc[0]
    real_efe     = caja_dia['EFECTIVO'].iloc[0]
    real_digital = caja_dia['DEBITO'].iloc[0]

    dif_efectivo  = (real_efe - inicio_caja) - teorico_efectivo
    dif_digital   = real_digital - teorico_digital
    balance_total = dif_efectivo + dif_digital

    return {
        'fecha': fecha.strftime('%d/%m/%Y'),
        'teorico_efectivo': teorico_efectivo, 'teorico_digital': teorico_digital,
        'inicio_caja': inicio_caja, 'real_efe': real_efe, 'real_digital': real_digital,
        'dif_efectivo': dif_efectivo, 'dif_digital': dif_digital,
        'balance_total': balance_total, 'gastos_dia': gastos_dia,
        'total_gastos_efe': total_gastos_efe, 'gestoria_dia': gestoria_dia,
        'total_gestoria': total_gestoria,
    }

def generar_pdf_cierre_A(datos):
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
    for label, ancho in zip(['VIRTUAL','EFECTIVO','VIRTUAL','EFECTIVO','VIRTUAL','EFECTIVO','TOTAL'], sub_anchos):
        pdf.cell(ancho, h, label, border=1, align='C', fill=True)
    pdf.ln()

    pdf.set_x(x_start)
    pdf.set_font("Arial", size=9)
    for valor, ancho in zip([datos['teorico_digital'], datos['teorico_efectivo'],
                              datos['real_digital'], datos['real_efe'],
                              datos['dif_digital'], datos['dif_efectivo']], sub_anchos[:-1]):
        pdf.cell(ancho, h, f"$ {valor:,.2f}", border=1, align='C')
    pdf.set_font("Arial", 'B', 9)
    pdf.cell(sub_anchos[-1], h, f"$ {datos['balance_total']:,.2f}", border=1, align='C')
    pdf.ln(15)

    pdf.set_font("Arial", 'I', 8)
    pdf.set_text_color(130, 130, 130)
    pdf.set_x(x_start)
    pdf.cell(0, 6, f"* Inicio de caja descontado: $ {datos['inicio_caja']:,.2f}", ln=True)
    pdf.ln(4)

    if not datos['gestoria_dia'].empty:
        nombres = ', '.join(sorted(datos['gestoria_dia']['GESTORIA'].unique()))
        pdf.multi_cell(0, 6,
            f"* Se consideraron como ya abonados los trámites del día de: {nombres}. "
            f"Monto total: $ {datos['total_gestoria']:,.2f}.", align='C')
        pdf.ln(6)

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
            pdf.cell(70, h, f"$ {gasto['COSTO']:,.2f}", border=1, align='R')
            pdf.ln()
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(120, h, "TOTAL GASTOS", border=1, align='R')
        pdf.cell(70, h, f"$ {datos['total_gastos_efe']:,.2f}", border=1, align='R')
        pdf.ln(10)

    pdf.set_font("Arial", 'B', 11)
    pdf.set_text_color(0, 0, 0)
    bt = datos['balance_total']
    if bt == 0:
        pdf.set_text_color(0, 128, 0)
        mensaje = "La caja cerró correctamente."
    else:
        pdf.set_text_color(255, 0, 0)
        mensaje = f"La caja no cerró. Diferencia: $ {bt:,.2f}"
    pdf.multi_cell(0, 10, mensaje, align='C')
    return pdf_a_bytes(pdf)

# ══════════════════════════════════════════════════════════════════
# PARSERS
# ══════════════════════════════════════════════════════════════════

def parsear_sura_efectivo(archivo_pdf, nombre_pdf):
    try:
        with pdfplumber.open(archivo_pdf) as pdf:
            texto = "\n".join(page.extract_text() for page in pdf.pages[-2:])
    except Exception:
        raise ValueError(f"No se pudo leer {nombre_pdf}.")

    # Patrón flexible: busca el número después de "Efectivo" e "Importe:"
    patron = r'Forma de Pago:\s*Efectivo\s+Importe:\s*\$\s*([\d\.]+,\d+)'
    match  = re.search(patron, texto)
    if not match:
        raise ValueError(f"No se encontró 'Forma de Pago: Efectivo' en {nombre_pdf}.")
    return float(match.group(1).replace(',', '.'))

def parsear_csv_banco(archivo_csv, df_gestorías_banco, fecha):
    TITULAR = 'CASTRUCCIO FACUNDO'
    cols = ['Fecha','Descripcion','Origen','Debitos','Creditos','Grupo','Concepto',
            'Terminal','Observaciones','Comprobante','Nombre','Col12','Col13','Col14',
            'TipoMovimiento','Saldo','Extra']
    try:
        df = pd.read_csv(archivo_csv, sep=';', encoding='utf-8-sig',
                         skiprows=1, names=cols, header=None, on_bad_lines='warn')
    except Exception:
        raise ValueError("No se pudo leer el CSV bancario.")
    df = df.dropna(subset=['Fecha'])

    def limpiar(v):
        if pd.isna(v) or str(v).strip() in ('', '0'): return 0.0
        try: return float(str(v).replace('.','').replace(',','.'))
        except: return 0.0

    df['Creditos_num'] = df['Creditos'].apply(limpiar)
    df['Nombre']       = df['Nombre'].fillna('').astype(str).str.strip()
    df['Fecha_dt']     = pd.to_datetime(df['Fecha'], dayfirst=True, errors='coerce')
    df = df[df['Fecha_dt'].dt.date == fecha]

    aliases = df_gestorías_banco['ALIAS_BANCO'].astype(str).str.strip().tolist()
    excluir = [TITULAR] + aliases

    validos   = df[(df['Creditos_num'] > 0) & (~df['Nombre'].isin(excluir))]
    excluidos = df[(df['Creditos_num'] > 0) & (df['Nombre'].isin(excluir))]

    return {
        'total'    : validos['Creditos_num'].sum(),
        'detalle'  : validos[['Nombre','Creditos_num']].rename(columns={'Nombre':'Origen','Creditos_num':'Monto'}),
        'excluidos': excluidos[['Nombre','Creditos_num']].rename(columns={'Nombre':'Origen','Creditos_num':'Monto'}),
    }

# ══════════════════════════════════════════════════════════════════
# CIERRE B
# ══════════════════════════════════════════════════════════════════

def procesar_suats(archivo, fecha):
    nombre = archivo.name.lower()
    if 'sellos' in nombre:         tipo = 'SUATS Sellos'
    elif 'patentes' in nombre:     tipo = 'SUATS Patentes'
    elif 'infracciones' in nombre: tipo = 'SUATS Infracciones'
    else: raise ValueError(f"No se reconoce: {archivo.name}")

    df = pd.read_excel(archivo)
    df.columns = [c.strip() for c in df.columns]
    df['Fecha Consulta'] = pd.to_datetime(df['Fecha Consulta'], errors='coerce')
    df['Fecha Acción']   = pd.to_datetime(df['Fecha Acción'],   errors='coerce')
    df['Monto']          = df['Monto'].apply(limpiar_moneda)

    consultas = df[df['Fecha Consulta'].dt.date == fecha]
    pagos     = df[(df['Fecha Acción'].dt.date == fecha) & (df['Acción'].str.strip() == 'Comprobante de Pago')]

    n   = len(consultas)
    mc  = n * PRECIO_CONSULTA
    mp  = pagos['Monto'].sum()
    return {'tipo': tipo, 'n_consultas': n, 'monto_consult': mc, 'monto_pagos': mp, 'total': mc + mp}

def calcular_cierre_B(fecha, archivos_suats, pdf_aranceles, pdf_formularios,
                      csv_banco, df_caja, df_sistema, df_gestorías_banco):
    resultados_suats = [procesar_suats(a, fecha) for a in archivos_suats]
    total_suats      = sum(r['total'] for r in resultados_suats)

    ef_aranc = parsear_sura_efectivo(pdf_aranceles,   'PlanillaCaja.pdf')
    ef_form  = parsear_sura_efectivo(pdf_formularios, 'PlanillaCaja2.pdf')
    total_sura = ef_aranc + ef_form

    res_banco  = parsear_csv_banco(csv_banco, df_gestorías_banco, fecha)
    total_trf  = res_banco['total']

    sis = df_sistema[df_sistema['FECHA'] == pd.Timestamp(fecha)]
    if sis.empty:
        raise ValueError(f"No hay datos en SISTEMA para {fecha.strftime('%d/%m/%Y')}.")
    pat_arba = sis['PATENTES ARBA'].iloc[0]
    pat_caba = sis['PATENTES CABA'].iloc[0]
    total_pat = pat_arba + pat_caba

    caja = df_caja[df_caja['FECHA'] == pd.Timestamp(fecha)]
    if caja.empty:
        raise ValueError(f"No hay registro en CAJA para {fecha.strftime('%d/%m/%Y')}.")
    inicio = caja['INICIO DE CAJA'].iloc[0]
    efec   = caja['EFECTIVO'].iloc[0]
    deb    = caja['DEBITO'].iloc[0]

    total_sis  = total_sura + total_suats + total_pat
    total_caja = efec + deb + total_trf
    resultado  = (total_sis + inicio) - total_caja

    return {
        'fecha': fecha.strftime('%d/%m/%Y'),
        'efectivo_aranceles': ef_aranc, 'efectivo_formularios': ef_form, 'total_sura': total_sura,
        'resultados_suats': resultados_suats, 'total_suats': total_suats,
        'patentes_arba': pat_arba, 'patentes_caba': pat_caba, 'total_patentes': total_pat,
        'total_sistema': total_sis, 'inicio_caja': inicio,
        'efectivo': efec, 'debito': deb, 'total_transferencias': total_trf,
        'total_caja': total_caja, 'resultado': resultado,
        'detalle_banco': res_banco['detalle'], 'excluidos_banco': res_banco['excluidos'],
    }

def generar_pdf_cierre_B(datos, analisis_ia=None):
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

    anchos = [110, 80]

    # SISTEMA
    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, h, "SISTEMA — Lo que los sistemas registraron", ln=True)
    pdf.ln(2)
    for col, ancho in zip(['FUENTE', 'MONTO'], anchos):
        pdf.cell(ancho, h, col, border=1, align='C', fill=True)
    pdf.ln()

    pdf.set_font("Arial", size=8)
    for nombre_item, monto in [('SURA Aranceles (PDF)', datos['efectivo_aranceles']),
                                ('SURA Formularios (PDF)', datos['efectivo_formularios'])]:
        pdf.set_text_color(0, 0, 0)
        pdf.cell(anchos[0], h, nombre_item, border=1)
        pdf.cell(anchos[1], h, f"$ {monto:,.2f}", border=1, align='R', ln=True)

    for r in datos['resultados_suats']:
        pdf.set_text_color(0, 0, 0)
        pdf.cell(anchos[0], h, f"{r['tipo']} ({r['n_consultas']} consultas + pagos)", border=1)
        pdf.cell(anchos[1], h, f"$ {r['total']:,.2f}", border=1, align='R', ln=True)

    for nombre_item, monto in [('Patentes ARBA (manual)', datos['patentes_arba']),
                                ('Patentes CABA (manual)', datos['patentes_caba'])]:
        pdf.set_text_color(100, 100, 100)
        pdf.cell(anchos[0], h, nombre_item, border=1)
        pdf.cell(anchos[1], h, f"$ {monto:,.2f}", border=1, align='R', ln=True)

    pdf.set_font("Arial", 'B', 9)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(anchos[0], h, "TOTAL SISTEMA", border=1, align='R')
    pdf.cell(anchos[1], h, f"$ {datos['total_sistema']:,.2f}", border=1, align='R')
    pdf.ln(2)

    pdf.set_font("Arial", size=8)
    pdf.cell(anchos[0], h, "Inicio de caja", border=1)
    pdf.cell(anchos[1], h, f"$ {datos['inicio_caja']:,.2f}", border=1, align='R', ln=True)

    pdf.set_font("Arial", 'B', 9)
    total_ingresos = datos['total_sistema'] + datos['inicio_caja']
    pdf.cell(anchos[0], h, "TOTAL INGRESOS (Sistema + Inicio de caja)", border=1, align='R')
    pdf.cell(anchos[1], h, f"$ {total_ingresos:,.2f}", border=1, align='R')
    pdf.ln(8)

    # CAJA
    pdf.set_font("Arial", 'B', 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(0, h, "CAJA — Lo que hay físicamente", ln=True)
    pdf.ln(2)
    for col, ancho in zip(['CONCEPTO', 'MONTO'], anchos):
        pdf.cell(ancho, h, col, border=1, align='C', fill=True)
    pdf.ln()

    pdf.set_font("Arial", size=8)
    for concepto, monto in [("Efectivo contado", datos['efectivo']),
                             ("Débito (postnet)", datos['debito']),
                             ("Transferencias del día", datos['total_transferencias'])]:
        pdf.set_text_color(0, 0, 0)
        pdf.cell(anchos[0], h, concepto, border=1)
        pdf.cell(anchos[1], h, f"$ {monto:,.2f}", border=1, align='R', ln=True)

    pdf.set_font("Arial", 'B', 9)
    pdf.cell(anchos[0], h, "TOTAL CAJA", border=1, align='R')
    pdf.cell(anchos[1], h, f"$ {datos['total_caja']:,.2f}", border=1, align='R')
    pdf.ln(10)

    # RESULTADO
    pdf.set_font("Arial", 'B', 12)
    resultado = datos['resultado']
    if resultado == 0:
        pdf.set_text_color(0, 128, 0)
        mensaje = "La caja cerró correctamente según el sistema."
    elif resultado > 0:
        pdf.set_text_color(255, 0, 0)
        mensaje = f"El sistema registra un excedente de $ {resultado:,.2f}"
    else:
        pdf.set_text_color(255, 0, 0)
        mensaje = f"El sistema registra un faltante de $ {abs(resultado):,.2f}"
    pdf.multi_cell(0, 10, mensaje, align='C')

    pdf.ln(3)
    pdf.set_font("Arial", 'I', 8)
    pdf.set_text_color(130, 130, 130)
    pdf.multi_cell(0, 6,
        "* SURA: importe extraído automáticamente del PDF. "
        "* SUATS: consultas y pagos calculados desde los xlsx. "
        "* Patentes ARBA y CABA: ingresados manualmente en la hoja SISTEMA. "
        "* Transferencias: calculadas desde el CSV bancario, "
        "excluyendo cuentas propias y pagos de gestorías.", align='C')

    diag = generar_diagnostico(datos)
    if diag:
        agregar_diagnostico_al_pdf(pdf, datos, diag)

    if analisis_ia:
        agregar_analisis_ia_al_pdf(pdf, analisis_ia, datos['fecha'])

    return pdf_a_bytes(pdf)

# ══════════════════════════════════════════════════════════════════
# DIAGNÓSTICO
# ══════════════════════════════════════════════════════════════════

def generar_diagnostico(datos):
    resultado = datos['resultado']
    if resultado == 0:
        return None
    if resultado > 0:
        titulo = f"El sistema registra un excedente de $ {resultado:,.2f}"
        intro  = (f"El sistema registró $ {datos['total_sistema']:,.2f} pero la caja suma "
                  f"$ {datos['total_caja']:,.2f}. Hay $ {resultado:,.2f} más en el sistema.")
        causas = [
            "El efectivo fue contado por menos de lo real — recontá el efectivo.",
            "Algún pago con débito no fue registrado en la hoja CAJA.",
            "Alguna transferencia no fue incluida en el CSV bancario o fue excluida por error.",
        ]
    else:
        abs_res = abs(resultado)
        titulo  = f"El sistema registra un faltante de $ {abs_res:,.2f}"
        intro   = (f"La caja suma $ {datos['total_caja']:,.2f} pero el sistema registró "
                   f"$ {datos['total_sistema']:,.2f}. Hay $ {abs_res:,.2f} más en la caja.")
        causas = [
            "El efectivo fue contado por más de lo real — recontá el efectivo.",
            "Se registró un débito en la hoja CAJA que no ocurrió ese día.",
            "Se registró una transferencia en el CSV bancario que no corresponde a ese día "
            "o que debería estar excluida.",
        ]

    excluidos      = datos.get('excluidos_banco')
    nota_excluidos = None
    if excluidos is not None and not excluidos.empty:
        nota_excluidos = (
            f"Se excluyeron transferencias por $ {excluidos['Monto'].sum():,.2f} "
            f"({len(excluidos)} movimiento(s)). Si alguna exclusión fue incorrecta, "
            f"actualizá la hoja GESTORÍAS_BANCO."
        )
    return {'titulo': titulo, 'intro': intro, 'causas': causas, 'nota_excluidos': nota_excluidos}

def agregar_diagnostico_al_pdf(pdf, datos, diag):
    h = 10
    pdf.add_page()
    pdf.set_text_color(0, 0, 0)

    pdf.set_font("Arial", 'I', 10)
    pdf.cell(95, 10, f"Fecha: {datos['fecha']}", 0, 0, 'L')
    pdf.cell(95, 10, "Registro Capital 100", 0, 1, 'R')
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 14)
    pdf.set_text_color(255, 0, 0)
    pdf.cell(0, 12, "DIAGNÓSTICO DE CIERRE", ln=True, align='C')
    pdf.ln(5)

    pdf.set_font("Arial", 'B', 10)
    pdf.multi_cell(0, 8, diag['titulo'], align='C')
    pdf.ln(4)

    pdf.set_font("Arial", size=9)
    pdf.set_text_color(0, 0, 0)
    pdf.multi_cell(0, 7, diag['intro'])
    pdf.ln(6)

    pdf.set_font("Arial", 'B', 10)
    pdf.cell(0, h, "Causas probables:", ln=True)
    pdf.ln(2)
    pdf.set_font("Arial", size=9)
    for i, causa in enumerate(diag['causas'], 1):
        pdf.set_x(15)
        pdf.multi_cell(0, 7, f"{i}. {causa}")
        pdf.ln(1)

    if diag['nota_excluidos']:
        pdf.ln(4)
        pdf.set_font("Arial", 'I', 8)
        pdf.set_text_color(100, 100, 100)
        pdf.multi_cell(0, 6, f"Nota: {diag['nota_excluidos']}")

    detalle = datos.get('detalle_banco')
    if detalle is not None and not detalle.empty:
        pdf.ln(8)
        pdf.set_font("Arial", 'B', 10)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, h, "Transferencias consideradas:", ln=True)
        pdf.ln(2)
        pdf.set_font("Arial", 'B', 8)
        pdf.set_fill_color(240, 240, 240)
        for col, ancho in [('ORIGEN', 130), ('MONTO', 60)]:
            pdf.cell(ancho, h, col, border=1, align='C', fill=True)
        pdf.ln()
        pdf.set_font("Arial", size=8)
        for _, fila in detalle.iterrows():
            pdf.set_text_color(0, 0, 0)
            pdf.cell(130, h, str(fila['Origen']), border=1)
            pdf.cell(60, h, f"$ {fila['Monto']:,.2f}", border=1, align='R', ln=True)
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(130, h, "TOTAL", border=1, align='R')
        pdf.cell(60, h, f"$ {datos['total_transferencias']:,.2f}", border=1, align='R')
        pdf.ln(8)

    excluidos = datos.get('excluidos_banco')
    if excluidos is not None and not excluidos.empty:
        pdf.set_font("Arial", 'B', 10)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, h, "Transferencias excluidas:", ln=True)
        pdf.ln(2)
        pdf.set_font("Arial", 'B', 8)
        pdf.set_fill_color(240, 240, 240)
        for col, ancho in [('ORIGEN', 130), ('MONTO', 60)]:
            pdf.cell(ancho, h, col, border=1, align='C', fill=True)
        pdf.ln()
        pdf.set_font("Arial", size=8)
        for _, fila in excluidos.iterrows():
            pdf.set_text_color(100, 100, 100)
            pdf.cell(130, h, str(fila['Origen']), border=1)
            pdf.cell(60, h, f"$ {fila['Monto']:,.2f}", border=1, align='R', ln=True)

    pdf.ln(8)
    pdf.set_font("Arial", 'B', 10)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, h, "Próximo paso:", ln=True)
    pdf.set_font("Arial", size=9)
    pdf.multi_cell(0, 7,
        "Si luego de verificar los puntos anteriores el error persiste, "
        "utilizá el botón 'Analizar con IA' en la aplicación para un diagnóstico "
        "detallado que cruzará los archivos del sistema con los trámites anotados.")

# ══════════════════════════════════════════════════════════════════
# AGENTE IA
# ══════════════════════════════════════════════════════════════════

def extraer_texto_sura(archivo_pdf):
    with pdfplumber.open(archivo_pdf) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)

def analizar_con_ia(datos, df_total, fecha, pdf_aranceles_bytes, pdf_formularios_bytes):
    cliente = anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])

    texto_aranc = extraer_texto_sura(io.BytesIO(pdf_aranceles_bytes))
    texto_form  = extraer_texto_sura(io.BytesIO(pdf_formularios_bytes))

    tramites_dia = df_total[df_total['FECHA'] == pd.Timestamp(fecha)]
    tramites_str = tramites_dia[['TRAMITE','GESTORIA','N° RECIBO / DOMINIO',
                                  'REF','ARANCEL','SELLADO','ALTA/BAJA/INF.',
                                  'IMPORTE TOTAL']].to_string(index=False)

    detalle_banco   = datos['detalle_banco'].to_string(index=False) if not datos['detalle_banco'].empty else "Sin transferencias"
    excluidos_banco = datos['excluidos_banco'].to_string(index=False) if not datos['excluidos_banco'].empty else "Ninguno"

    suats_str = ""
    for r in datos['resultados_suats']:
        suats_str += (f"\n{r['tipo']}:\n  Consultas: {r['n_consultas']} "
                      f"($ {r['monto_consult']:,.2f})\n  Pagos: $ {r['monto_pagos']:,.2f}\n"
                      f"  Total: $ {r['total']:,.2f}\n")

    contexto = f"""
Sos un asistente experto en auditoría de registros automotores argentinos.
Analizá el cierre de caja del {datos['fecha']} e identificá las discrepancias.

RESULTADO: $ {datos['resultado']:,.2f}
({'Sistema registra MÁS' if datos['resultado'] > 0 else 'Caja tiene MÁS'})
Total sistema: $ {datos['total_sistema']:,.2f} | Total caja: $ {datos['total_caja']:,.2f}

TRÁMITES ANOTADOS EN LA PLANILLA:
{tramites_str}

TRANSFERENCIAS BANCARIAS CONSIDERADAS:
{detalle_banco}

EXCLUIDAS (cuentas propias y gestorías):
{excluidos_banco}

DATOS SUATS:
{suats_str}

PLANILLA SURA ARANCELES:
{texto_aranc}

PLANILLA SURA FORMULARIOS:
{texto_form}

INSTRUCCIONES:
1. Compará dominios y N° de recibo de SURA con los anotados en la planilla.
2. Compará dominios de SUATS con los anotados.
3. Identificá trámites en el sistema que no aparecen en la planilla.
4. Listá discrepancias con: N° recibo/dominio, tipo de trámite, monto, sistema origen.

Respondé en español. Empezá con un resumen ejecutivo de 1-2 oraciones.
"""

    respuesta = cliente.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        messages=[{"role": "user", "content": contexto}]
    )
    return respuesta.content[0].text

def agregar_analisis_ia_al_pdf(pdf, analisis_texto, fecha_str):
    pdf.add_page()
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", 'I', 10)
    pdf.cell(95, 10, f"Fecha: {fecha_str}", 0, 0, 'L')
    pdf.cell(95, 10, "Registro Capital 100", 0, 1, 'R')
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 14)
    pdf.set_text_color(0, 80, 160)
    pdf.cell(0, 12, "ANÁLISIS DE DISCREPANCIAS — IA", ln=True, align='C')
    pdf.ln(5)
    pdf.set_font("Arial", size=9)
    pdf.set_text_color(0, 0, 0)
    for parrafo in analisis_texto.split('\n'):
        parrafo = parrafo.strip()
        if not parrafo:
            pdf.ln(3)
            continue
        if parrafo.startswith('═') or parrafo.startswith('—'):
            pdf.ln(2)
            continue
        if parrafo.endswith(':') and len(parrafo) < 60:
            pdf.set_font("Arial", 'B', 9)
            pdf.multi_cell(0, 6, parrafo)
            pdf.set_font("Arial", size=9)
        else:
            pdf.multi_cell(0, 6, parrafo)

# ══════════════════════════════════════════════════════════════════
# DEUDAS
# ══════════════════════════════════════════════════════════════════

def calcular_deudas(df_total, df_pagos):
    deudas = {}
    for gestoria, grupo in df_total[df_total['GESTORIA'] != 'Particular'].groupby('GESTORIA'):
        importe_total  = grupo['IMPORTE TOTAL'].sum()
        pagos          = df_pagos[df_pagos['GESTORIA'] == gestoria]['MONTO'].sum()
        deuda_neta     = importe_total - pagos
        if deuda_neta > 0:
            deudas[gestoria] = {
                'tipo': 'GESTORIA', 'total': deuda_neta,
                'importe_total': importe_total, 'pagos': pagos,
                'detalle': grupo[['FECHA','TRAMITE','REF','N° RECIBO / DOMINIO','IMPORTE TOTAL']].sort_values('FECHA'),
                'detalle_pagos': df_pagos[df_pagos['GESTORIA'] == gestoria][['FECHA','MONTO']].sort_values('FECHA'),
            }
    particulares = df_total[(df_total['GESTORIA'] == 'Particular') & (df_total['DEBE'] > 0)]
    if not particulares.empty:
        deudas['Particular'] = {
            'tipo': 'PARTICULAR', 'total': particulares['DEBE'].sum(),
            'detalle': particulares[['FECHA','TRAMITE','REF','N° RECIBO / DOMINIO','IMPORTE TOTAL','DEBE']].sort_values('FECHA'),
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
            tiene_ref = datos['detalle']['REF'].apply(lambda v: pd.notna(v) and str(v).strip() not in ('', 'nan')).any()
            pdf.set_font("Arial", 'B', 9)
            pdf.cell(0, 8, "Trámites realizados:", ln=True)
            pdf.set_font("Arial", 'B', 8)
            pdf.set_fill_color(240, 240, 240)

            if tiene_ref:
                columnas = ['FECHA','TRAMITE','REF','N° / DOMINIO','IMPORTE TOTAL']
                anchos   = [25, 35, 30, 30, 70]
            else:
                columnas = ['FECHA','TRAMITE','N° / DOMINIO','IMPORTE TOTAL']
                anchos   = [25, 40, 40, 85]

            for col, ancho in zip(columnas, anchos):
                pdf.cell(ancho, 10, col, border=1, align='C', fill=True)
            pdf.ln()

            pdf.set_font("Arial", size=8)
            for _, fila in datos['detalle'].iterrows():
                pdf.set_text_color(0, 0, 0)
                pdf.cell(anchos[0], 10, fila['FECHA'].strftime('%d/%m/%Y'), border=1, align='C')
                pdf.cell(anchos[1], 10, str(fila['TRAMITE']), border=1)
                if tiene_ref:
                    ref = str(fila['REF']) if pd.notna(fila.get('REF')) and str(fila.get('REF')).strip() not in ('','nan') else '-'
                    pdf.cell(anchos[2], 10, ref, border=1)
                    pdf.cell(anchos[3], 10, str(fila['N° RECIBO / DOMINIO']), border=1)
                    pdf.cell(anchos[4], 10, f"$ {fila['IMPORTE TOTAL']:,.2f}", border=1, align='R', ln=True)
                else:
                    pdf.cell(anchos[2], 10, str(fila['N° RECIBO / DOMINIO']), border=1)
                    pdf.cell(anchos[3], 10, f"$ {fila['IMPORTE TOTAL']:,.2f}", border=1, align='R', ln=True)

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
                    pdf.cell(25, 10, pago['FECHA'].strftime('%d/%m/%Y'), border=1, align='C')
                    pdf.set_text_color(0, 128, 0)
                    pdf.cell(165, 10, f"$ {pago['MONTO']:,.2f}", border=1, align='R', ln=True)
                pdf.set_font("Arial", 'B', 9)
                pdf.set_text_color(0, 128, 0)
                pdf.cell(25, 10, "TOTAL PAGADO", border=1, align='R')
                pdf.cell(165, 10, f"$ {datos['pagos']:,.2f}", border=1, align='R')
                pdf.ln(10)

            pdf.set_font("Arial", 'B', 11)
            pdf.set_text_color(200, 0, 0)
            pdf.cell(espaciador, 10, "DEUDA NETA:", border=1, align='R')
            pdf.cell(anchos[-1], 10, f"$ {datos['total']:,.2f}", border=1, align='R')

        elif datos['tipo'] == 'PARTICULAR':
            tiene_ref = datos['detalle']['REF'].apply(lambda v: pd.notna(v) and str(v).strip() not in ('','nan')).any()
            pdf.set_font("Arial", 'B', 8)
            pdf.set_fill_color(240, 240, 240)

            if tiene_ref:
                columnas = ['FECHA','TRAMITE','REF','N° / DOMINIO','IMPORTE TOTAL','DEBE']
                anchos   = [25, 30, 25, 25, 45, 40]
            else:
                columnas = ['FECHA','TRAMITE','N° / DOMINIO','IMPORTE TOTAL','DEBE']
                anchos   = [25, 35, 35, 45, 50]

            for col, ancho in zip(columnas, anchos):
                pdf.cell(ancho, 10, col, border=1, align='C', fill=True)
            pdf.ln()

            pdf.set_font("Arial", size=8)
            for _, fila in datos['detalle'].iterrows():
                pdf.set_text_color(0, 0, 0)
                pdf.cell(anchos[0], 10, fila['FECHA'].strftime('%d/%m/%Y'), border=1, align='C')
                pdf.cell(anchos[1], 10, str(fila['TRAMITE']), border=1)
                if tiene_ref:
                    ref = str(fila['REF']) if pd.notna(fila.get('REF')) and str(fila.get('REF')).strip() not in ('','nan') else '-'
                    pdf.cell(anchos[2], 10, ref, border=1)
                    pdf.cell(anchos[3], 10, str(fila['N° RECIBO / DOMINIO']), border=1)
                    pdf.cell(anchos[4], 10, f"$ {fila['IMPORTE TOTAL']:,.2f}", border=1, align='R')
                    pdf.set_text_color(200, 0, 0)
                    pdf.cell(anchos[5], 10, f"$ {fila['DEBE']:,.2f}", border=1, align='R', ln=True)
                else:
                    pdf.cell(anchos[2], 10, str(fila['N° RECIBO / DOMINIO']), border=1)
                    pdf.cell(anchos[3], 10, f"$ {fila['IMPORTE TOTAL']:,.2f}", border=1, align='R')
                    pdf.set_text_color(200, 0, 0)
                    pdf.cell(anchos[4], 10, f"$ {fila['DEBE']:,.2f}", border=1, align='R', ln=True)

            pdf.set_font("Arial", 'B', 10)
            pdf.set_text_color(0, 0, 0)
            espaciador = sum(anchos[:-2])
            pdf.cell(espaciador, 10, "", 0)
            pdf.set_text_color(200, 0, 0)
            pdf.cell(anchos[-2], 10, "TOTAL ADEUDADO:", 0, 0, 'R')
            pdf.cell(anchos[-1], 10, f"$ {datos['total']:,.2f}", border=1, align='R')

    return pdf_a_bytes(pdf)

# ══════════════════════════════════════════════════════════════════
# INTERFAZ
# ══════════════════════════════════════════════════════════════════

st.title("🏢 Registro Capital 100")
st.caption("Sistema de cierre de caja")

password = st.text_input("Contraseña:", type="password")
if password != st.secrets["PASSWORD"]:
    st.warning("Ingresá la contraseña para continuar.")
    st.stop()

with st.sidebar:
    st.header("Menú")
    seccion = st.radio("", ["📄 PDF Gestorías", "🧾 Cierre de Caja", "💰 Estado de Deudas"],
                       label_visibility="collapsed")
    st.divider()
    if st.button("🔄 Actualizar datos"):
        st.cache_data.clear()
        st.rerun()
    st.caption("Datos actualizados cada 5 minutos.")
    st.divider()
    st.markdown(f"[📊 Abrir Google Sheets](https://docs.google.com/spreadsheets/d/{SHEET_ID})")

with st.spinner("Cargando datos..."):
    df_total, df_pagos, df_gastos, df_caja, df_sistema, df_gestorías_banco = cargar_datos()

st.success(f"✅ {len(df_total)} trámites cargados.")
st.divider()

# ── PDF GESTORÍAS ────────────────────────────────────────────────
if seccion == "📄 PDF Gestorías":
    st.header("📄 PDF de Gestorías")
    fecha = st.date_input("Fecha:", value=date.today(), format="DD/MM/YYYY")

    if st.button("Generar PDFs", type="primary"):
        fecha_ts  = pd.Timestamp(fecha)
        datos_dia = df_total[df_total['FECHA'] == fecha_ts]
        gestoras  = datos_dia[datos_dia['GESTORIA'] != 'Particular']['GESTORIA'].unique()

        if len(gestoras) == 0:
            st.warning(f"No hay trámites de gestorías para el {fecha.strftime('%d/%m/%Y')}.")
        else:
            for gestoria in sorted(gestoras):
                try:
                    pdf_bytes = generar_pdf_gestoria(gestoria, fecha_ts, datos_dia[datos_dia['GESTORIA'] == gestoria])
                    nombre    = f"Reporte_{sanitizar_nombre(gestoria)}_{fecha.strftime('%d-%m-%Y')}.pdf"
                    st.download_button(f"⬇️ {gestoria}", data=pdf_bytes, file_name=nombre,
                                       mime="application/pdf", key=f"pdf_{gestoria}")
                    st.success(f"✅ {nombre}")
                except Exception as ex:
                    st.error(f"❌ Error en {gestoria}: {ex}")

# ── CIERRE DE CAJA ───────────────────────────────────────────────
elif seccion == "🧾 Cierre de Caja":
    st.header("🧾 Cierre de Caja")

    fecha = st.date_input("Fecha:", value=date.today(), format="DD/MM/YYYY")

    modo_manual = st.toggle("⚠️ Ingresar valores manualmente (usar solo si hay problemas con los archivos)")
    st.divider()

    # Session state
    for key in ['datos_cierre_b', 'analisis_ia', 'pdf_aranc_bytes', 'pdf_form_bytes']:
        if key not in st.session_state:
            st.session_state[key] = None

    # ── Modo automático ──────────────────────────────────────────
    if not modo_manual:
        st.subheader("Archivos requeridos")
        col1, col2 = st.columns(2)
        with col1:
            archivos_suats = st.file_uploader("📊 SUATS (sellos, patentes, infracciones):",
                                               type="xlsx", accept_multiple_files=True)
            if archivos_suats:
                for a in archivos_suats:
                    n = a.name.lower()
                    etiqueta = "✅ Sellos" if 'sellos' in n else "✅ Patentes" if 'patentes' in n \
                               else "✅ Infracciones" if 'infracciones' in n else "⚠️ No reconocido"
                    st.write(f"{etiqueta} — `{a.name}`")
            csv_banco = st.file_uploader("🏦 CSV bancario:", type="csv")
            if csv_banco: st.write(f"✅ `{csv_banco.name}`")

        with col2:
            pdf_aranceles = st.file_uploader("📄 PlanillaCaja.pdf:", type="pdf", key="pdf_aranc")
            if pdf_aranceles: st.write(f"✅ `{pdf_aranceles.name}`")
            pdf_formularios = st.file_uploader("📄 PlanillaCaja2.pdf:", type="pdf", key="pdf_form")
            if pdf_formularios: st.write(f"✅ `{pdf_formularios.name}`")

        st.divider()
        todo_subido = all([archivos_suats, csv_banco, pdf_aranceles, pdf_formularios])

        if st.button("Generar Cierre de Caja", type="primary", disabled=not todo_subido):
            try:
                aranc_bytes = pdf_aranceles.read()
                form_bytes  = pdf_formularios.read()

                datos = calcular_cierre_B(
                    fecha, archivos_suats,
                    io.BytesIO(aranc_bytes), io.BytesIO(form_bytes),
                    csv_banco, df_caja, df_sistema, df_gestorías_banco
                )
                st.session_state.datos_cierre_b  = datos
                st.session_state.analisis_ia     = None
                st.session_state.pdf_aranc_bytes = aranc_bytes
                st.session_state.pdf_form_bytes  = form_bytes

                col1, col2, col3 = st.columns(3)
                col1.metric("Total sistema", f"$ {datos['total_sistema']:,.2f}")
                col2.metric("Total caja",    f"$ {datos['total_caja']:,.2f}")
                col3.metric("Resultado",     f"$ {datos['resultado']:,.2f}")

                if datos['resultado'] == 0:
                    st.success("✅ La caja cerró correctamente.")
                else:
                    diag = generar_diagnostico(datos)
                    st.error(f"❌ {diag['titulo']}")
                    st.write(diag['intro'])
                    with st.expander("📋 Ver causas probables"):
                        for i, causa in enumerate(diag['causas'], 1):
                            st.write(f"{i}. {causa}")
                        if diag['nota_excluidos']:
                            st.info(f"ℹ️ {diag['nota_excluidos']}")

                st.download_button("⬇️ Descargar PDF de cierre",
                                   data=generar_pdf_cierre_B(datos),
                                   file_name=f"Cierre_{fecha.strftime('%d-%m-%Y')}.pdf",
                                   mime="application/pdf", key="dl_cierre_b")

            except ValueError as ex:
                st.warning(f"⚠️ {ex}")
            except Exception as ex:
                st.error(f"❌ Error: {ex}")

    # ── Modo manual ──────────────────────────────────────────────
    else:
        st.warning("Modo manual activo. Ingresá los valores que normalmente se leen de los archivos.")

        st.subheader("Valores del sistema")
        col1, col2 = st.columns(2)
        with col1:
            m_sura_aranc = st.number_input("SURA Aranceles ($):",      min_value=0.0, step=1000.0, format="%.2f")
            m_sura_form  = st.number_input("SURA Formularios ($):",    min_value=0.0, step=1000.0, format="%.2f")
            m_suats_sel  = st.number_input("SUATS Sellos ($):",        min_value=0.0, step=1000.0, format="%.2f")
        with col2:
            m_suats_pat  = st.number_input("SUATS Patentes ($):",      min_value=0.0, step=1000.0, format="%.2f")
            m_suats_inf  = st.number_input("SUATS Infracciones ($):",  min_value=0.0, step=1000.0, format="%.2f")
            m_pat_arba   = st.number_input("Patentes ARBA ($):",       min_value=0.0, step=1000.0, format="%.2f")
            m_pat_caba   = st.number_input("Patentes CABA ($):",       min_value=0.0, step=1000.0, format="%.2f")

        st.subheader("Valores de caja")
        col1, col2, col3 = st.columns(3)
        with col1:
            m_inicio = st.number_input("Inicio de caja ($):",      min_value=0.0, step=1000.0, format="%.2f")
        with col2:
            m_efec   = st.number_input("Efectivo contado ($):",    min_value=0.0, step=1000.0, format="%.2f")
        with col3:
            m_deb    = st.number_input("Débito postnet ($):",       min_value=0.0, step=1000.0, format="%.2f")

        m_trf = st.number_input("Transferencias del día ($):", min_value=0.0, step=1000.0, format="%.2f")

        st.divider()

        if st.button("Generar Cierre de Caja", type="primary", key="btn_manual"):
            # Construimos el dict de datos manualmente con la misma estructura que calcular_cierre_B()
            total_sura   = m_sura_aranc + m_sura_form
            total_suats  = m_suats_sel + m_suats_pat + m_suats_inf
            total_pat    = m_pat_arba + m_pat_caba
            total_sis    = total_sura + total_suats + total_pat
            total_caja   = m_efec + m_deb + m_trf
            resultado    = (total_sis + m_inicio) - total_caja

            datos = {
                'fecha'               : fecha.strftime('%d/%m/%Y'),
                'efectivo_aranceles'  : m_sura_aranc,
                'efectivo_formularios': m_sura_form,
                'total_sura'          : total_sura,
                'resultados_suats'    : [
                    {'tipo': 'SUATS Sellos',       'n_consultas': 0, 'monto_consult': 0, 'monto_pagos': m_suats_sel, 'total': m_suats_sel},
                    {'tipo': 'SUATS Patentes',     'n_consultas': 0, 'monto_consult': 0, 'monto_pagos': m_suats_pat, 'total': m_suats_pat},
                    {'tipo': 'SUATS Infracciones', 'n_consultas': 0, 'monto_consult': 0, 'monto_pagos': m_suats_inf, 'total': m_suats_inf},
                ],
                'total_suats'         : total_suats,
                'patentes_arba'       : m_pat_arba,
                'patentes_caba'       : m_pat_caba,
                'total_patentes'      : total_pat,
                'total_sistema'       : total_sis,
                'inicio_caja'         : m_inicio,
                'efectivo'            : m_efec,
                'debito'              : m_deb,
                'total_transferencias': m_trf,
                'total_caja'          : total_caja,
                'resultado'           : resultado,
                'detalle_banco'       : pd.DataFrame(columns=['Origen', 'Monto']),
                'excluidos_banco'     : pd.DataFrame(columns=['Origen', 'Monto']),
            }
            st.session_state.datos_cierre_b  = datos
            st.session_state.analisis_ia     = None
            st.session_state.pdf_aranc_bytes = None
            st.session_state.pdf_form_bytes  = None

            col1, col2, col3 = st.columns(3)
            col1.metric("Total sistema", f"$ {total_sis:,.2f}")
            col2.metric("Total caja",    f"$ {total_caja:,.2f}")
            col3.metric("Resultado",     f"$ {resultado:,.2f}")

            if resultado == 0:
                st.success("✅ La caja cerró correctamente.")
            else:
                diag = generar_diagnostico(datos)
                st.error(f"❌ {diag['titulo']}")
                st.write(diag['intro'])
                with st.expander("📋 Ver causas probables"):
                    for i, causa in enumerate(diag['causas'], 1):
                        st.write(f"{i}. {causa}")

            st.download_button("⬇️ Descargar PDF de cierre",
                               data=generar_pdf_cierre_B(datos),
                               file_name=f"Cierre_{fecha.strftime('%d-%m-%Y')}_manual.pdf",
                               mime="application/pdf", key="dl_cierre_manual")

    # ── Botón IA (aplica a ambos modos si no cerró) ──────────────
    datos_b = st.session_state.datos_cierre_b
    if datos_b is not None and datos_b['resultado'] != 0:
        st.divider()
        st.subheader("🤖 Análisis con IA")
        st.write("Si ya verificaste los puntos del diagnóstico y el error persiste, "
                 "el agente de IA cruzará todos los archivos e identificará las discrepancias específicas.")

        # El análisis IA solo está disponible en modo automático (necesita los PDFs)
        if st.session_state.pdf_aranc_bytes is None:
            st.info("ℹ️ El análisis con IA no está disponible en modo manual porque requiere los PDFs de SURA.")
        else:
            if st.button("🔍 Analizar con IA", type="primary"):
                try:
                    with st.spinner("🤖 Analizando... (puede tardar unos segundos)"):
                        analisis = analizar_con_ia(
                            datos_b, df_total, fecha,
                            st.session_state.pdf_aranc_bytes,
                            st.session_state.pdf_form_bytes
                        )
                        st.session_state.analisis_ia = analisis

                    st.markdown("### Resultado del análisis")
                    st.markdown(analisis)

                    st.download_button("⬇️ Descargar PDF con análisis IA",
                                       data=generar_pdf_cierre_B(datos_b, analisis_ia=analisis),
                                       file_name=f"Cierre_IA_{fecha.strftime('%d-%m-%Y')}.pdf",
                                       mime="application/pdf", key="dl_ia")
                except Exception as ex:
                    st.error(f"❌ Error al consultar la IA: {ex}")

            elif st.session_state.analisis_ia:
                st.markdown("### Último análisis generado")
                st.markdown(st.session_state.analisis_ia)

# ── DEUDAS ───────────────────────────────────────────────────────
elif seccion == "💰 Estado de Deudas":
    st.header("💰 Estado de Deudas")
    deudas = calcular_deudas(df_total, df_pagos)

    if not deudas:
        st.success("✅ No hay deudas pendientes.")
    else:
        st.metric("Total general adeudado", f"$ {sum(d['total'] for d in deudas.values()):,.2f}")
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
                st.download_button("⬇️ Descargar PDF",
                                   data=generar_pdf_deudas(deudas),
                                   file_name=f"Deudas_{hoy.strftime('%d-%m-%Y')}.pdf",
                                   mime="application/pdf")
            except Exception as ex:
                st.error(f"❌ Error: {ex}")
