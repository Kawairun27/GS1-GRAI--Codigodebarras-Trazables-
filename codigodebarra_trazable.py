import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
from fpdf import FPDF

# --- NUEVA FUNCIÓN: VALIDACIÓN DE DÍGITO DE CONTROL GS1 ---
def validar_digito_control_gs1(codigo_completo):
    """
    Calcula el dígito de control para los primeros 12 dígitos 
    (excluyendo el dígito en la posición 13 y el serial).
    Algoritmo: Multiplicar posiciones impares por 3 y pares por 1.
    """
    try:
        # Extraemos la parte numérica fija del GRAI (los 12 dígitos antes del de control)
        # Asumiendo formato: 8003 + 0 + Prefijo + Tipo
        cuerpo = codigo_completo.replace("(", "").replace(")", "")
        if len(cuerpo) < 13: return False
        
        parte_fija = cuerpo[4:16] # Los 12 dígitos para el cálculo
        digito_proporcionado = int(cuerpo[16])
        
        # Algoritmo GS1
        suma = 0
        for i, digito in enumerate(reversed(parte_fija)):
            n = int(digito)
            if i % 2 == 0: # Posición impar desde la derecha (1ra, 3ra...)
                suma += n * 3
            else: # Posición par desde la derecha
                suma += n * 1
        
        proximo_multiplo_10 = (suma + 9) // 10 * 10
        digito_calculado = proximo_multiplo_10 - suma
        
        return digito_calculado == digito_proporcionado
    except Exception:
        return False

# --- CONFIGURACIÓN DE BASE DE DATOS ---
Base = declarative_base()

class Activo(Base):
    __tablename__ = 'activos'
    id = Column(Integer, primary_key=True)
    grai = Column(String(30), unique=True) # Global Returnable Asset Identifier
    tipo = Column(String(100)) # Ejemplo: Palet Plástico, Contenedor Químico
    ciclos_uso = Column(Integer, default=0)
    estado_actual = Column(String(50))
    escaneos = relationship("HistorialEscaneo", back_populates="activo")

class HistorialEscaneo(Base):
    __tablename__ = 'historial_escaneos'
    id = Column(Integer, primary_key=True)
    fecha = Column(DateTime, default=datetime.utcnow)
    evento = Column(String(100)) # Salida a Cliente, Retorno, Higienización
    observacion = Column(String(200))
    activo_id = Column(Integer, ForeignKey('activos.id'))
    activo = relationship("Activo", back_populates="escaneos")

engine = create_engine('sqlite:///logistica_inversa_rd.db')
Base.metadata.all_all = Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
db = Session()

# --- FUNCIONES DE APOYO ---
def generar_pdf(activo, historial):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"HISTORIAL DE TRAZABILIDAD - ACTIVO {activo.grai}", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 10, f"Tipo: {activo.tipo} | Ciclos Totales: {activo.ciclos_uso}", ln=True, align="C")
    pdf.ln(5)
    
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(40, 10, "Fecha", border=1)
    pdf.cell(60, 10, "Evento", border=1)
    pdf.cell(90, 10, "Observaciones", border=1)
    pdf.ln()
    
    pdf.set_font("Helvetica", "", 9)
    for h in historial:
        pdf.cell(40, 10, h.fecha.strftime("%d/%m/%y %H:%M"), border=1)
        pdf.cell(60, 10, h.evento, border=1)
        pdf.cell(90, 10, h.observacion, border=1)
        pdf.ln()
    return pdf.output()

# --- INTERFAZ STREAMLIT ---
st.set_page_config(page_title="TechArmor RD - Logística Inversa", layout="wide")
st.title("🔄 Gestión de Activos Retornables (GRAI)")
st.markdown("### Trazabilidad de Ciclos de Uso y Mantenimiento")

menu = st.sidebar.radio("Navegación", ["Escanear Activo", "Registrar Nuevo Activo", "Inventario y Alertas", "Reportes"])

# --- SECCIÓN 1: ESCANEAR ACTIVO (Lo que querías ver en tu celular) ---
if menu == "Escanear Activo":
    st.header("📸 Escaneo de Activo en Tiempo Real")
    
    # Simulación de escaneo: En el celular aparecerá la cámara
    img_file = st.camera_input("Apunta al código de barras o QR")
    
    input_metodo = st.radio("¿Cómo ingresar el código?", ["Manual / Escáner Externo", "Cámara (Simulado)"])
    
    codigo_detectado = ""
    if input_metodo == "Manual / Escáner Externo":
        codigo_detectado = st.text_input("Ingresa el código GRAI:")
    
    if codigo_detectado:
        activo = db.query(Activo).filter(Activo.grai == codigo_detectado).first()
        
        if activo:
            st.success(f"Activo Encontrado: {activo.tipo}")
            col1, col2, col3 = st.columns(3)
            col1.metric("Ciclos de Uso", activo.ciclos_uso)
            col2.metric("Estado Actual", activo.estado_actual)
            col3.metric("Límite Mantenimiento", "50 ciclos")

            if activo.ciclos_uso >= 45:
                st.warning("⚠️ ESTE ACTIVO REQUIERE REVISIÓN TÉCNICA PRONTO")

            st.subheader("Registrar Nuevo Movimiento")
            with st.form("nuevo_mov"):
                evento = st.selectbox("Evento", ["Salida a Cliente", "Retorno de Cliente", "Higienización", "Mantenimiento"])
                obs = st.text_input("Observaciones (Ej: Lote de jabón, Nombre del Cliente)")
                if st.form_submit_button("Actualizar Trazabilidad"):
                    # Lógica de negocio: si es retorno, aumentar ciclo
                    if evento == "Retorno de Cliente":
                        activo.ciclos_uso += 1
                    
                    activo.estado_actual = "Limpio" if evento == "Higienización" else "En Uso"
                    nuevo_h = HistorialEscaneo(evento=evento, observacion=obs, activo_id=activo.id)
                    db.add(nuevo_h)
                    db.commit()
                    st.rerun()
        else:
            st.error("Activo no registrado en la base de datos.")

# --- SECCIÓN 2: REGISTRO (MODIFICADA CON VALIDACIÓN) ---
if menu == "Registrar Nuevo Activo":
    st.header("🆕 Registro de Activos con Norma GS1")
    st.info("Formato sugerido: (8003)0746123401[Dígito de Control][Serial]")
    
    with st.form("reg_activo"):
        grai_input = st.text_input("Código GRAI Completo", placeholder="(8003)074612340170001")
        tipo = st.selectbox("Tipo de Activo", ["Palet Plástico Azul", "Contenedor IBC 1000L", "Caja Térmica"])
        
        submit = st.form_submit_button("Validar y Guardar")
        
        if submit:
            if validar_digito_control_gs1(grai_input):
                nuevo = Activo(grai=grai_input, tipo=tipo, estado_actual="Disponible", ciclos_uso=0)
                db.add(nuevo)
                db.commit()
                st.success("✅ Código Válido bajo Norma GS1. Activo registrado.")
            else:
                st.error("❌ Error de Trazabilidad: El Dígito de Control GS1 no coincide. Verifique la estructura del código.")

# --- SECCIÓN 3: INVENTARIO ---
elif menu == "Inventario y Alertas":
    st.header("📊 Tablero de Control de Activos")
    query = db.query(Activo).all()
    if query:
        df = pd.DataFrame([{
            "GRAI": a.grai, "Tipo": a.tipo, "Ciclos": a.ciclos_uso, "Estado": a.estado_actual
        } for a in query])
        st.table(df)
        
        st.subheader("Alertas de Ingeniería")
        criticos = [a for a in query if a.ciclos_uso > 40]
        if criticos:
            for c in criticos:
                st.error(f"ALERTA: Activo {c.grai} tiene {c.ciclos_uso} ciclos. Programar retiro.")
        else:
            st.info("Todos los activos están dentro del rango operativo seguro.")

# --- SECCIÓN 4: REPORTES ---
elif menu == "Reportes":
    st.header("📄 Certificados de Trazabilidad")
    activos = db.query(Activo).all()
    seleccion = st.selectbox("Selecciona un activo para generar su historial PDF", [a.grai for a in activos])
    
    if st.button("Descargar Reporte Completo"):
        activo_obj = db.query(Activo).filter(Activo.grai == seleccion).first()
        historial = db.query(HistorialEscaneo).filter(HistorialEscaneo.activo_id == activo_obj.id).all()
        
        pdf_bytes = generar_pdf(activo_obj, historial)
        st.download_button("Descargar PDF", data=bytes(pdf_bytes), file_name=f"Trazabilidad_{seleccion}.pdf")