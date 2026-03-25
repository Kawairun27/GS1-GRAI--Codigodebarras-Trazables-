import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
from PIL import Image
from pyzbar.pyzbar import decode

# --- FUNCIONES DE APOYO Y VALIDACIÓN ---

def limpiar_codigo(codigo):
    if not codigo: return ""
    return "".join(filter(str.isdigit, str(codigo)))

def decodificar_imagen(img_file):
    """Detecta y lee el contenido de un código QR o DataMatrix."""
    try:
        img = Image.open(img_file)
        resultados = decode(img)
        if resultados:
            # Retornamos el contenido del primer código detectado
            return resultados[0].data.decode("utf-8")
        return None
    except Exception as e:
        st.error(f"Error al procesar la imagen: {e}")
        return None

def calcular_modulo_10(cadena_datos):
    suma = 0
    for i, digito in enumerate(reversed(cadena_datos)):
        n = int(digito)
        suma += n * 3 if i % 2 == 0 else n * 1
    resultado = (10 - (suma % 10)) % 10
    return resultado

def validar_digito_control_gs1(codigo_completo):
    try:
        cuerpo = limpiar_codigo(codigo_completo)
        if not cuerpo.startswith("8003") or len(cuerpo) < 17:
            return False
        datos = cuerpo[4:16]      
        control_real = int(cuerpo[16]) 
        return calcular_modulo_10(datos) == control_real
    except Exception:
        return False

def identificar_familia(codigo):
    cuerpo = limpiar_codigo(codigo)
    if len(cuerpo) < 16: return "Desconocido"
    familia = cuerpo[14:16] 
    if familia == "01": return "Palet Plástico Azul"
    elif familia == "02": return "Caja Térmica"
    elif familia == "03": return "Contenedor IBC 1000L"
    else: return "Otro Activo"

# --- CONFIGURACIÓN DE BASE DE DATOS ---
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
    fecha = Column(DateTime, default=datetime.utcnow)
    evento = Column(String(100))
    observacion = Column(String(200))
    activo_id = Column(Integer, ForeignKey('activos.id'))
    activo = relationship("Activo", back_populates="escaneos")

engine = create_engine('sqlite:///logistica_inversa_rd.db')
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
db = Session()

# --- INTERFAZ STREAMLIT ---
st.set_page_config(page_title="TechArmor RD", layout="wide")
st.title("🔄 Gestión de Activos Retornables (GRAI)")

menu = st.sidebar.radio("Navegación", ["Escanear Activo", "Registrar Nuevo Activo", "Inventario", "Reportes"])

if menu == "Escanear Activo":
    st.header("📸 Escaneo de Activo")
    input_metodo = st.radio("Entrada:", ["Cámara", "Manual / Escáner"])
    
    codigo_detectado = ""
    
    if input_metodo == "Cámara":
        img_file = st.camera_input("Capturar código QR / DataMatrix")
        if img_file:
            # Intentamos extraer el texto de la imagen capturada
            codigo_detectado = decodificar_imagen(img_file)
            if codigo_detectado:
                st.success(f"Código detectado: {codigo_detectado}")
            else:
                st.warning("No se detectó ningún código. Asegúrate de que haya buena luz y el código esté centrado.")
    else:
        codigo_detectado = st.text_input("Ingresa o pega el código:")

    if codigo_detectado:
        busqueda = limpiar_codigo(codigo_detectado)
        # Limpieza para búsqueda (extraer cuerpo si trae el IA 8003)
        if busqueda.startswith("8003"): 
            busqueda_db = busqueda[4:16]
        else:
            busqueda_db = busqueda
        
        activo = db.query(Activo).filter(Activo.grai.contains(busqueda_db)).first()
        
        if activo:
            st.info(f"Activo Identificado: {activo.tipo} | GRAI: {activo.grai}")
            with st.form("mov"):
                evento = st.selectbox("Actualizar Estado / Acción", 
                                    ["Salida a Cliente", "Retorno de Cliente", "Higienización", "Mantenimiento"])
                if st.form_submit_button("Confirmar Movimiento"):
                    if evento == "Retorno de Cliente": 
                        activo.ciclos_uso += 1
                    activo.estado_actual = evento # Actualiza el estado actual del activo
                    db.add(HistorialEscaneo(evento=evento, activo_id=activo.id))
                    db.commit()
                    st.success("Trazabilidad y estado actualizados.")
                    st.rerun()
        else:
            st.error("El código detectado no coincide con ningún activo en el inventario.")

elif menu == "Registrar Nuevo Activo":
    # [Se mantiene igual que tu versión anterior por ser correcta]
    st.header("🆕 Registro por Familia de Activo")
    st.info("Familias: 01=Palet, 02=Caja, 03=IBC")
    with st.form("reg"):
        grai_input = st.text_input("Código GRAI", placeholder="Ej: 80030746123400012")
        tipo_detectado = identificar_familia(grai_input)
        st.write(f"**Análisis:** Familia detectada: {tipo_detectado}")
        tipo_final = st.selectbox("Confirmar Tipo de Activo", ["Palet Plástico Azul", "Caja Térmica", "Contenedor IBC 1000L"])
        if st.form_submit_button("Validar e Insertar"):
            if validar_digito_control_gs1(grai_input):
                try:
                    nuevo = Activo(grai=grai_input, tipo=tipo_final, estado_actual="Disponible")
                    db.add(nuevo)
                    db.commit()
                    st.success(f"✅ {tipo_final} registrado.")
                except:
                    st.error("Este código ya existe.")
            else:
                cuerpo = limpiar_codigo(grai_input)
                if len(cuerpo) >= 16:
                    sugerido = calcular_modulo_10(cuerpo[4:16])
                    st.error(f"❌ Dígito inválido. Debería ser: {sugerido}")

elif menu == "Inventario":
    # [Se mantiene igual que tu versión anterior]
    st.header("📊 Inventario Actual")
    activos = db.query(Activo).all()
    if activos:
        for a in activos:
            with st.expander(f"📦 {a.tipo} - {a.grai}"):
                col1, col2, col3 = st.columns(3)
                col1.metric("Ciclos", a.ciclos_uso)
                col2.write(f"**Estado:** {a.estado_actual}")
                if col3.button("🗑️ Eliminar", key=f"del_{a.id}"):
                    db.delete(a)
                    db.commit()
                    st.rerun()

elif menu == "Reportes":
    # [Se mantiene igual que tu versión anterior]
    st.header("📄 Historial de Trazabilidad")
    activos_list = db.query(Activo).all()
    if activos_list:
        seleccion = st.selectbox("Selecciona un activo:", [f"{a.id} - {a.tipo} ({a.grai})" for a in activos_list])
        id_activo = seleccion.split(" - ")[0]
        historial = db.query(HistorialEscaneo).filter_by(activo_id=id_activo).all()
        if historial:
            st.table(pd.DataFrame([{"Fecha": h.fecha, "Evento": h.evento} for h in historial]))