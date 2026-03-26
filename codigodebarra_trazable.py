import streamlit as st
import pandas as pd
import cv2
import numpy as np
import zxingcpp
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime, timedelta
from fpdf import FPDF
import io
import altair as alt

# --- FUNCIONES DE APOYO Y VALIDACIÓN ---

def generar_pdf_inventario_completo(activos):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "REPORTE GLOBAL DE INVENTARIO - TECHARMOR RD", ln=True, align="C")
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 10, f"Fecha de corte: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")
    pdf.ln(10)

    familias = {}
    for a in activos:
        if a.tipo not in familias:
            familias[a.tipo] = []
        familias[a.tipo].append(a)

    for familia, lista_activos in familias.items():
        pdf.set_fill_color(200, 220, 255)
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 10, f" FAMILIA: {familia.upper()} ({len(lista_activos)} unidades)", ln=True, fill=True)
        
        pdf.set_font("Arial", "B", 10)
        pdf.cell(60, 8, "ID GRAI", border=1)
        pdf.cell(60, 8, "Estado Actual", border=1)
        pdf.cell(30, 8, "Ciclos", border=1, align="C")
        pdf.cell(40, 8, "Salud", border=1, align="C")
        pdf.ln()

        pdf.set_font("Arial", "", 9)
        for a in lista_activos:
            salud = "CRITICO" if a.ciclos_uso >= 3 else "OPTIMO"
            pdf.cell(60, 8, str(a.grai), border=1)
            pdf.cell(60, 8, str(a.estado_actual), border=1)
            pdf.cell(30, 8, str(a.ciclos_uso), border=1, align="C")
            pdf.cell(40, 8, salud, border=1, align="C")
            pdf.ln()
        pdf.ln(5)

    return pdf.output(dest='S').encode('latin-1')

def limpiar_codigo(codigo):
    if not codigo: return ""
    codigo_str = str(codigo).replace("<GS>", "").strip()
    return "".join(filter(str.isdigit, codigo_str))

def decodificar_imagen(img_file):
    try:
        file_bytes = np.asarray(bytearray(img_file.read()), dtype=np.uint8)
        img = cv2.imdecode(file_bytes, 1)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        resultados = zxingcpp.read_barcodes(gray)
        if resultados: return resultados[0].text
        resultados_color = zxingcpp.read_barcodes(img)
        if resultados_color: return resultados_color[0].text
        return None
    except Exception as e:
        st.error(f"Error técnico: {e}")
        return None

def calcular_modulo_10(cadena_datos):
    suma = 0
    for i, digito in enumerate(reversed(cadena_datos)):
        n = int(digito)
        suma += n * 3 if i % 2 == 0 else n * 1
    return (10 - (suma % 10)) % 10

def validar_digito_control_gs1(codigo_completo):
    try:
        cuerpo = limpiar_codigo(codigo_completo)
        if not cuerpo.startswith("8003") or len(cuerpo) < 17: return False
        datos = cuerpo[4:16]      
        control_real = int(cuerpo[16]) 
        return calcular_modulo_10(datos) == control_real
    except: return False

def identificar_familia(codigo):
    cuerpo = limpiar_codigo(codigo)
    if len(cuerpo) < 16: return "Otro Activo"
    familia = cuerpo[14:16] 
    mapping = {"01": "Palet Plástico Azul", "02": "Caja Térmica", "03": "Contenedor IBC 1000L"}
    return mapping.get(familia, "Otro Activo")

def generar_pdf_trazabilidad(activo, historial):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "CERTIFICADO DE TRAZABILIDAD - TECHARMOR RD", ln=True, align="C")
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 10, f"Generado el: {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True, align="C")
    pdf.ln(5)
    
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, f" Datos del Activo", ln=True, fill=True)
    pdf.set_font("Arial", "", 10)
    pdf.cell(0, 7, f"ID GRAI: {activo.grai}", ln=True)
    pdf.cell(0, 7, f"Tipo: {activo.tipo}", ln=True)
    pdf.cell(0, 7, f"Ciclos de Uso Acumulados: {activo.ciclos_uso}", ln=True)
    pdf.ln(5)
    
    pdf.set_font("Arial", "B", 10)
    pdf.cell(45, 10, "Fecha y Hora", border=1, align="C")
    pdf.cell(65, 10, "Evento / Accion", border=1, align="C")
    pdf.cell(80, 10, "Origen / Destino", border=1, align="C") 
    pdf.ln()
    
    pdf.set_font("Arial", "", 9)
    # El historial ya viene en orden descendente desde la consulta
    for h in historial:
        pdf.cell(45, 10, h.fecha.strftime("%d/%m/%Y %H:%M"), border=1)
        pdf.cell(65, 10, f" {h.evento}", border=1)
        
        # Lógica visual para clarificar flujo en el reporte
        if h.evento == "Retorno de Cliente":
            texto_lugar = f"Desde: {h.destino}" if h.destino else "N/A"
        elif h.evento == "Salida a Cliente":
            texto_lugar = f"Hacia: {h.destino}" if h.destino else "N/A"
        else:
            texto_lugar = "Planta / Interno"
            
        pdf.cell(80, 10, f" {texto_lugar}", border=1)
        pdf.ln()
    
    return pdf.output(dest='S').encode('latin-1')

# --- BASE DE DATOS ---
Base = declarative_base()
class Activo(Base):
    __tablename__ = 'activos'
    id = Column(Integer, primary_key=True)
    grai = Column(String(50), unique=True)
    tipo = Column(String(100))
    ciclos_uso = Column(Integer, default=0)
    estado_actual = Column(String(50))
    escaneos = relationship("HistorialEscaneo", back_populates="activo", cascade="all, delete-orphan")

class HistorialEscaneo(Base):
    __tablename__ = 'historial_escaneos'
    id = Column(Integer, primary_key=True)
    fecha = Column(DateTime, default=lambda: datetime.now()) 
    evento = Column(String(100))
    destino = Column(String(100), nullable=True)
    activo_id = Column(Integer, ForeignKey('activos.id'))
    activo = relationship("Activo", back_populates="escaneos")

engine = create_engine('sqlite:///logistica_inversa_rd.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
db = Session()

# --- INTERFAZ ---
st.set_page_config(page_title="TechArmor RD", layout="wide")
st.title("🔄 TechArmor RD: Gestión de Activos")

menu = st.sidebar.radio("Navegación", ["Escanear Activo", "Registrar Nuevo Activo", "Inventario", "Reportes"])

if menu == "Escanear Activo":
    st.header("📸 Escaneo de Activo")
    input_metodo = st.radio("Entrada:", ["Cámara", "Manual / Escáner"], horizontal=True)
    codigo_detectado = ""
    
    if input_metodo == "Cámara":
        img_file = st.camera_input("Capturar QR o DataMatrix")
        if img_file:
            codigo_detectado = decodificar_imagen(img_file)
            if codigo_detectado: st.success(f"✅ Detectado: {codigo_detectado}")
    else:
        codigo_detectado = st.text_input("Ingresa el código:")

    if codigo_detectado:
        busqueda = limpiar_codigo(codigo_detectado)
        busqueda_db = busqueda[4:16] if busqueda.startswith("8003") else busqueda
        activo = db.query(Activo).filter(Activo.grai.contains(busqueda_db)).first()
        
        if activo:
            # --- LÓGICA DE BLOQUEO INDUSTRIAL ---
            esta_bloqueado = "Bloqueado" in activo.estado_actual or "Mantenimiento" in activo.estado_actual
            necesita_mantenimiento = activo.ciclos_uso >= 3
            
            st.info(f"📦 Activo: {activo.tipo} | Ciclos: {activo.ciclos_uso}/3 | Estado: {activo.estado_actual}")
            
            # Definimos qué opciones mostrar según el estado real del activo
            opciones_validas = []
            
            if activo.estado_actual == "En Taller (Bloqueado)":
                st.warning("⚠️ Este activo está en mantenimiento técnico. Solo puede pasar a Higienización al terminar.")
                opciones_validas = ["Higienización"]
            elif necesita_mantenimiento:
                st.error("🚨 LÍMITE DE CICLOS ALCANZADO. El activo debe ir a Mantenimiento obligatoriamente.")
                opciones_validas = ["Mantenimiento"]
            elif activo.estado_actual == "Salida a Cliente":
                opciones_validas = ["Retorno de Cliente"]
            else:
                # Flujo normal para activos disponibles o en retorno (que no han llegado a 3 ciclos)
                opciones_validas = ["Salida a Cliente", "Mantenimiento", "Higienización"]

            evento = st.selectbox("Acción Permitida", opciones_validas, key="sel_evento")
            
            with st.form("mov"):
                destino_input = ""
                
                if evento == "Salida a Cliente":
                    destino_input = st.text_input("Empresa Destino / Cliente:", placeholder="Ej: Supermercados Nacional")
                
                elif evento == "Retorno de Cliente":
                    ultimo_envio = db.query(HistorialEscaneo).filter_by(activo_id=activo.id, evento="Salida a Cliente").order_by(HistorialEscaneo.fecha.desc()).first()
                    if ultimo_envio and ultimo_envio.destino:
                        destino_input = ultimo_envio.destino
                        st.success(f"Detectado retorno desde: **{destino_input}**")
                    else:
                        destino_input = st.text_input("Origen del retorno (Manual):")

                if st.form_submit_button("Actualizar Trazabilidad"):
                    # --- APLICACIÓN DE REGLAS DE ESTADO CON RESETEO CONDICIONAL ---
                    if evento == "Retorno de Cliente": 
                        activo.ciclos_uso += 1
                        if activo.ciclos_uso >= 3:
                            activo.estado_actual = "Mantenimiento Requerido (Bloqueado)"
                        else:
                            activo.estado_actual = "Retorno de Cliente"
                    
                    elif evento == "Mantenimiento":
                        activo.estado_actual = "En Taller (Bloqueado)"
                    
                    elif evento == "Higienización":
                        # NUEVA CONDICIÓN DE RESETEO DE INGENIERÍA
                        if activo.ciclos_uso >= 3:
                            activo.ciclos_uso = 0  # Solo resetea si cumplió su vida útil
                            st.balloons()
                            st.success("✅ Mantenimiento Mayor Completado: Ciclos reseteados.")
                        else:
                            st.info("🧼 Limpieza de rutina completada. Los ciclos se mantienen.")
                        
                        activo.estado_actual = "Disponible"
                    
                    else:
                        activo.estado_actual = evento 

                    db.add(HistorialEscaneo(evento=evento, activo_id=activo.id, destino=destino_input))
                    db.commit()
                    st.success(f"Movimiento procesado: {activo.estado_actual}")
                    st.rerun()
        else: st.error("No registrado.")
elif menu == "Registrar Nuevo Activo":
    st.header("🆕 Registro de Activo")
    codigo_camara = ""
    img_file_reg = st.camera_input("Escanear para registrar")
    if img_file_reg:
        codigo_camara = decodificar_imagen(img_file_reg)
    
    grai_input = st.text_input("Código GRAI (17 dígitos)", value=limpiar_codigo(codigo_camara))
    tipo_sugerido = identificar_familia(grai_input)
    opciones = ["Palet Plástico Azul", "Caja Térmica", "Contenedor IBC 1000L", "Otro Activo"]
    idx = opciones.index(tipo_sugerido) if tipo_sugerido in opciones else 3

    with st.form("reg"):
        tipo_final = st.selectbox("Confirmar Tipo", opciones, index=idx)
        if st.form_submit_button("Registrar"):
            if validar_digito_control_gs1(grai_input):
                try:
                    nuevo = Activo(grai=limpiar_codigo(grai_input), tipo=tipo_final, estado_actual="Disponible")
                    db.add(nuevo)
                    db.commit()
                    st.success("Registrado correctamente.")
                except: st.error("Ya existe.")
            else: st.error("Código o Dígito de control inválido.")

elif menu == "Inventario":
    st.header("📊 Panel de Control y Estado de Flota")
    activos = db.query(Activo).all()
    
    if not activos:
        st.info("No hay activos registrados aún.")
    else:
        total = len(activos)
        en_cliente = len([a for a in activos if a.estado_actual == "Salida a Cliente"])
        criticos = [a for a in activos if a.ciclos_uso >= 3]
        disponibles = len([a for a in activos if a.estado_actual == "Disponible"])

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("📦 Total Flota", total)
        c2.metric("🚚 En Cliente", en_cliente)
        c3.metric("🚨 Mantenimiento", len(criticos), delta=len(criticos), delta_color="inverse")
        c4.metric("✅ Listos", disponibles)

        st.divider()

        col_left, col_right = st.columns([2, 1])
        with col_left:
            st.subheader("Distribución por Estado")
            counts = pd.DataFrame([a.estado_actual for a in activos], columns=["Estado"]).value_counts().reset_index()
            counts.columns = ["Estado", "Cantidad"]
    
            max_val = int(counts['Cantidad'].max())
            tick_values = list(range(0, max_val + 1))

            chart = alt.Chart(counts).mark_bar(color="#1f77b4").encode(
                x=alt.X('Cantidad:Q', 
                        axis=alt.Axis(values=tick_values, format='d'), 
                        title='Número de Activos'),
                y=alt.Y('Estado:N', title='Estado Actual', sort='-x'),
                tooltip=['Estado', 'Cantidad']
            ).properties(height=300)
    
            st.altair_chart(chart, use_container_width=True)
        
        with col_right:
            st.subheader("Resumen de Salud")
            st.write(f"🟢 Operativos: {total - len(criticos)}")
            st.write(f"🔴 Críticos: {len(criticos)}")
            if criticos:
                st.warning("Atención: Unidades requieren revisión.")

        st.divider()

        st.subheader("🔍 Detalle de Activos")
        filtro = st.multiselect("Filtrar por estado:", 
                               options=["Disponible", "Salida a Cliente", "Retorno de Cliente", "Higienización", "Mantenimiento"],
                               default=[])
        
        for a in activos:
            if not filtro or a.estado_actual in filtro:
                es_critico = a.ciclos_uso >= 3
                color = "red" if es_critico else "blue"
                emoji = "🚨" if es_critico else "📦"
                
                with st.expander(f"{emoji} {a.tipo} | ID: {a.grai}"):
                    col_info, col_bar, col_btn = st.columns([2, 2, 1])
                    with col_info:
                        st.write(f"**Estado:** :{color}[{a.estado_actual}]")
                        st.write(f"**Ciclos:** {a.ciclos_uso} / 3")
                    with col_bar:
                        progreso = min(a.ciclos_uso / 3, 1.0)
                        st.progress(progreso, text="Uso de vida útil")
                    with col_btn:
                        if st.button("Eliminar", key=f"del_{a.id}", use_container_width=True):
                            db.delete(a); db.commit(); st.rerun()

elif menu == "Reportes":
    st.header("📄 Centro de Inteligencia y Trazabilidad")
    activos_list = db.query(Activo).all()
    
    if not activos_list:
        st.info("No hay activos registrados para generar reportes.")
    else:
        st.subheader("📊 Reporte de Inventario Completo")
        pdf_global_bytes = generar_pdf_inventario_completo(activos_list)
        
        st.download_button(
            label="📥 Descargar Inventario por Familias (PDF)",
            data=pdf_global_bytes,
            file_name=f"Inventario_Global_{datetime.now().strftime('%d-%m-%Y')}.pdf",
            mime="application/pdf",
            key="btn_global"
        )
        
        st.divider()

        st.subheader("🔍 Localizar Activo Individual")
        col_busqueda, col_filtro_tipo = st.columns([2, 1])
        
        with col_filtro_tipo:
            tipos_disponibles = ["Todos"] + list(set([a.tipo for a in activos_list]))
            filtro_tipo = st.selectbox("Filtrar por familia:", tipos_disponibles)
        
        with col_busqueda:
            activos_filtrados = [a for a in activos_list if filtro_tipo == "Todos" or a.tipo == filtro_tipo]
            opciones_dict = {f"ID: {a.grai} | {a.tipo}": a.id for a in activos_filtrados}
            seleccion_label = st.selectbox(
                "Escribe el ID o selecciona:",
                options=[""] + list(opciones_dict.keys()),
                format_func=lambda x: "🔎 Selecciona un activo..." if x == "" else x
            )

        if seleccion_label != "":
            id_act = opciones_dict[seleccion_label]
            activo_obj = db.query(Activo).get(id_act)
            # ORDEN DESCENDENTE EN LA CONSULTA
            historial = db.query(HistorialEscaneo).filter_by(activo_id=id_act).order_by(HistorialEscaneo.fecha.desc()).all()

            st.info(f"Visualizando: **{activo_obj.tipo}** - GRAI: `{activo_obj.grai}`")
            
            if historial:
                pdf_ind_bytes = generar_pdf_trazabilidad(activo_obj, historial)
                
                st.download_button(
                    label="📥 Descargar Certificado de este Activo",
                    data=pdf_ind_bytes,
                    file_name=f"Trazabilidad_{activo_obj.grai}.pdf",
                    mime="application/pdf",
                    key=f"btn_ind_{activo_obj.id}"
                )

                df_hist = pd.DataFrame([{"Fecha": h.fecha.strftime("%d/%m/%Y %H:%M"), 
                                         "Evento": h.evento,
                                         "Ubicación / Cliente": h.destino if h.destino else "Planta"} for h in historial])
                st.table(df_hist)
            else:
                st.warning("Este activo no tiene movimientos registrados.")