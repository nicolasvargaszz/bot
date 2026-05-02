#!/usr/bin/env python3
"""
Generador de Leads v2 - Sistema Mejorado
Ordena por probabilidad de compra, incluye todos los datos de contacto
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# Configuración
LEADS_POR_LOTE = 30
PROJECT_ROOT = Path(__file__).resolve().parents[3]
LEGACY_DATA_PATH = PROJECT_ROOT / "data" / "legacy" / "datos_definitivos_final.json"
DATABASE_PATH = PROJECT_ROOT / "data" / "processed" / "ventas_v2.db"
SUMMARY_PATH = PROJECT_ROOT / "data" / "processed" / "resumen_leads_v2.json"

# Pesos para el score de compra (0-100)
PESOS = {
    'reviews': 25,      # Muchos reviews = negocio activo
    'rating': 15,       # Buen rating = cuida su imagen
    'sin_web': 20,      # SIN website = NECESITA uno
    'categoria': 20,    # Categorías que invierten en marketing
    'fotos': 10,        # Fotos = cuida presencia
    'redes_sociales': 10  # Tiene redes = entiende marketing digital
}

CATEGORIAS_PREMIUM = {
    # Máxima prioridad - alto margen, cuidan imagen
    "Restaurante": 100, "Bar": 95, "Pizzería": 90, "Cafetería": 85,
    "Hamburguesería": 80, "Heladería": 75, "Pastelería": 70,
    # Alta prioridad - servicios personales
    "Spa": 90, "Centro de estética": 85, "Peluquería": 80, "Barbería": 75,
    "Gimnasio": 70, "Clínica dental": 85, "Veterinario": 75,
    # Media prioridad
    "Hotel": 80, "Tienda de ropa": 65, "Tienda de productos para mascotas": 60,
    "Panadería": 55, "Lavadero de autos": 50, "Florería": 60,
    "Tienda de electrónica": 55, "Imprenta": 50
}


def cargar_datos():
    """Carga los datos de negocios"""
    with open(LEGACY_DATA_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def calcular_score_compra(negocio):
    """
    Calcula probabilidad de compra (0-100)
    Mayor score = más probable que compre
    """
    score = 0
    detalles = {}
    
    # 1. Reviews (25 puntos) - Más reviews = negocio más activo
    reviews = negocio.get('review_count') or 0
    if reviews >= 500:
        score_reviews = 25
    elif reviews >= 200:
        score_reviews = 20
    elif reviews >= 100:
        score_reviews = 15
    elif reviews >= 50:
        score_reviews = 10
    elif reviews >= 20:
        score_reviews = 5
    else:
        score_reviews = 2
    score += score_reviews
    detalles['reviews'] = score_reviews
    
    # 2. Rating (15 puntos) - Buen rating = cuida su imagen
    rating = negocio.get('rating') or 0
    if rating >= 4.5:
        score_rating = 15
    elif rating >= 4.0:
        score_rating = 12
    elif rating >= 3.5:
        score_rating = 8
    elif rating >= 3.0:
        score_rating = 4
    else:
        score_rating = 0
    score += score_rating
    detalles['rating'] = score_rating
    
    # 3. SIN Website (20 puntos) - NECESITA uno = oportunidad
    has_website = negocio.get('has_website', False)
    if not has_website:
        score_web = 20  # No tiene = QUIERE uno
    else:
        score_web = 5   # Tiene pero puede querer mejorar
    score += score_web
    detalles['sin_web'] = score_web
    
    # 4. Categoría (20 puntos)
    categoria = negocio.get('category', 'Otro')
    score_cat = CATEGORIAS_PREMIUM.get(categoria, 30) * 0.20  # Escala a 20 puntos max
    score += score_cat
    detalles['categoria'] = round(score_cat, 1)
    
    # 5. Fotos (10 puntos) - Cuida su presencia visual
    fotos = len(negocio.get('photo_urls', []))
    if fotos >= 10:
        score_fotos = 10
    elif fotos >= 5:
        score_fotos = 7
    elif fotos >= 2:
        score_fotos = 4
    else:
        score_fotos = 0
    score += score_fotos
    detalles['fotos'] = score_fotos
    
    # 6. Redes sociales (10 puntos) - Entiende marketing digital
    redes = negocio.get('social_media', {})
    tiene_instagram = bool(redes.get('instagram'))
    tiene_facebook = bool(redes.get('facebook'))
    if tiene_instagram and tiene_facebook:
        score_redes = 10
    elif tiene_instagram or tiene_facebook:
        score_redes = 6
    else:
        score_redes = 0
    score += score_redes
    detalles['redes'] = score_redes
    
    return round(score, 1), detalles


def extraer_leads_completos(datos):
    """Extrae leads con toda la información útil"""
    leads = []
    
    for i, negocio in enumerate(datos):
        # Solo incluir si tiene teléfono (necesario para contactar)
        if not negocio.get('phone'):
            continue
        
        score, score_detalles = calcular_score_compra(negocio)
        redes = negocio.get('social_media', {})
        
        lead = {
            'id': i,
            'nombre': negocio.get('name', 'Sin nombre'),
            'categoria': negocio.get('category', 'Otro'),
            
            # Contacto
            'telefono': negocio.get('phone'),
            'instagram': redes.get('instagram'),
            'facebook': redes.get('facebook'),
            'website_actual': negocio.get('website_url'),
            'tiene_web': negocio.get('has_website', False),
            
            # Ubicación
            'direccion': negocio.get('address', ''),
            'ciudad': negocio.get('city', 'Asunción'),
            'barrio': negocio.get('neighborhood', ''),
            'google_maps': f"https://www.google.com/maps/place/?q=place_id:{negocio.get('google_place_id', '')}",
            
            # Métricas
            'rating': negocio.get('rating', 0),
            'reviews': negocio.get('review_count', 0),
            'fotos': len(negocio.get('photo_urls', [])),
            'rango_precio': negocio.get('price_range', ''),
            
            # Score de compra
            'score_compra': score,
            'score_detalles': json.dumps(score_detalles),
            
            # Info adicional útil
            'horarios': json.dumps(negocio.get('opening_hours', {})),
            'servicios': ', '.join(negocio.get('offerings', [])[:5]),
            
            # Seguimiento
            'estado': 'pendiente',
            'lote': None,
            'fecha_asignacion': None,
            'fecha_contacto': None,
            'resultado_llamada': None,
            'notas': '',
            'recordatorio': None
        }
        leads.append(lead)
    
    return leads


def asignar_lotes_por_score(leads, leads_por_lote=LEADS_POR_LOTE):
    """Asigna leads a lotes, ordenados por score de compra (mejores primero)"""
    
    # Ordenar por score de compra (mayor primero)
    leads_ordenados = sorted(leads, key=lambda x: -x['score_compra'])
    
    fecha_inicio = datetime.now()
    lote_actual = 1
    
    for i, lead in enumerate(leads_ordenados):
        lead['lote'] = lote_actual
        lead['fecha_asignacion'] = (fecha_inicio + timedelta(days=lote_actual-1)).strftime('%Y-%m-%d')
        
        if (i + 1) % leads_por_lote == 0:
            lote_actual += 1
    
    return leads_ordenados


def init_db_v2():
    """Inicializa la base de datos mejorada"""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY,
            nombre TEXT NOT NULL,
            categoria TEXT,
            
            -- Contacto
            telefono TEXT,
            instagram TEXT,
            facebook TEXT,
            website_actual TEXT,
            tiene_web BOOLEAN,
            
            -- Ubicación
            direccion TEXT,
            ciudad TEXT,
            barrio TEXT,
            google_maps TEXT,
            
            -- Métricas
            rating REAL,
            reviews INTEGER,
            fotos INTEGER,
            rango_precio TEXT,
            
            -- Score
            score_compra REAL,
            score_detalles TEXT,
            
            -- Info adicional
            horarios TEXT,
            servicios TEXT,
            
            -- Seguimiento
            estado TEXT DEFAULT 'pendiente',
            lote INTEGER,
            fecha_asignacion TEXT,
            fecha_contacto TEXT,
            resultado_llamada TEXT,
            notas TEXT,
            recordatorio TEXT,
            
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS llamadas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER,
            fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            duracion_segundos INTEGER,
            resultado TEXT,
            notas TEXT,
            siguiente_accion TEXT,
            fecha_seguimiento TEXT,
            FOREIGN KEY (lead_id) REFERENCES leads (id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS estadisticas_diarias (
            fecha TEXT PRIMARY KEY,
            llamadas_realizadas INTEGER DEFAULT 0,
            contactos_exitosos INTEGER DEFAULT 0,
            interesados INTEGER DEFAULT 0,
            demos_agendadas INTEGER DEFAULT 0,
            ventas_cerradas INTEGER DEFAULT 0
        )
    ''')
    
    conn.commit()
    conn.close()


def guardar_leads_db(leads):
    """Guarda leads en SQLite"""
    init_db_v2()
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Limpiar tabla existente
    cursor.execute('DELETE FROM leads')
    
    for lead in leads:
        cursor.execute('''
            INSERT INTO leads (
                id, nombre, categoria, telefono, instagram, facebook,
                website_actual, tiene_web, direccion, ciudad, barrio,
                google_maps, rating, reviews, fotos, rango_precio,
                score_compra, score_detalles, horarios, servicios,
                estado, lote, fecha_asignacion
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            lead['id'], lead['nombre'], lead['categoria'],
            lead['telefono'], lead['instagram'], lead['facebook'],
            lead['website_actual'], lead['tiene_web'],
            lead['direccion'], lead['ciudad'], lead['barrio'],
            lead['google_maps'], lead['rating'], lead['reviews'],
            lead['fotos'], lead['rango_precio'], lead['score_compra'],
            lead['score_detalles'], lead['horarios'], lead['servicios'],
            lead['estado'], lead['lote'], lead['fecha_asignacion']
        ))
    
    conn.commit()
    conn.close()
    print(f"✅ {len(leads)} leads guardados en {DATABASE_PATH}")


def generar_resumen(leads):
    """Genera resumen detallado"""
    if not leads:
        return {
            'total_leads': 0,
            'total_lotes': 0,
            'score_promedio_general': 0,
            'con_instagram': 0,
            'con_facebook': 0,
            'sin_website': 0,
            'lotes': {}
        }

    total_lotes = max(l['lote'] for l in leads) if leads else 0
    
    # Estadísticas por lote
    lotes_info = {}
    for lead in leads:
        lote = lead['lote']
        if lote not in lotes_info:
            lotes_info[lote] = {
                'total': 0,
                'score_promedio': 0,
                'con_instagram': 0,
                'con_facebook': 0,
                'sin_web': 0,
                'fecha': lead['fecha_asignacion']
            }
        lotes_info[lote]['total'] += 1
        lotes_info[lote]['score_promedio'] += lead['score_compra']
        if lead['instagram']:
            lotes_info[lote]['con_instagram'] += 1
        if lead['facebook']:
            lotes_info[lote]['con_facebook'] += 1
        if not lead['tiene_web']:
            lotes_info[lote]['sin_web'] += 1
    
    # Calcular promedios
    for lote, info in lotes_info.items():
        info['score_promedio'] = round(info['score_promedio'] / info['total'], 1)
    
    resumen = {
        'total_leads': len(leads),
        'total_lotes': total_lotes,
        'score_promedio_general': round(sum(l['score_compra'] for l in leads) / len(leads), 1),
        'con_instagram': sum(1 for l in leads if l['instagram']),
        'con_facebook': sum(1 for l in leads if l['facebook']),
        'sin_website': sum(1 for l in leads if not l['tiene_web']),
        'lotes': lotes_info
    }
    
    return resumen


def main():
    print("🚀 Generador de Leads v2 - Por Score de Compra")
    print("=" * 50)
    
    # Cargar datos
    print("\n📂 Cargando datos...")
    datos = cargar_datos()
    print(f"   Total negocios: {len(datos)}")
    
    # Extraer leads
    print("\n🔍 Extrayendo leads con teléfono...")
    leads = extraer_leads_completos(datos)
    print(f"   Leads con teléfono: {len(leads)}")
    
    # Asignar lotes por score
    print("\n📊 Ordenando por probabilidad de compra...")
    leads_ordenados = asignar_lotes_por_score(leads)
    
    # Guardar en DB
    print("\n💾 Guardando en base de datos...")
    guardar_leads_db(leads_ordenados)
    
    # Resumen
    resumen = generar_resumen(leads_ordenados)
    print("\n" + "=" * 50)
    print("📈 RESUMEN")
    print("=" * 50)
    print(f"Total leads: {resumen['total_leads']}")
    print(f"Total lotes: {resumen['total_lotes']} (de {LEADS_POR_LOTE} leads c/u)")
    print(f"Score promedio: {resumen['score_promedio_general']}/100")
    print(f"Con Instagram: {resumen['con_instagram']}")
    print(f"Con Facebook: {resumen['con_facebook']}")
    print(f"SIN website (oportunidad): {resumen['sin_website']}")
    
    print("\n🔝 TOP 5 LOTES (mayor probabilidad de compra):")
    for i in range(1, min(6, resumen['total_lotes'] + 1)):
        info = resumen['lotes'][i]
        print(f"   Lote {i}: Score {info['score_promedio']}/100 | "
              f"{info['sin_web']} sin web | {info['con_instagram']} con IG")
    
    # Guardar resumen JSON
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SUMMARY_PATH, 'w', encoding='utf-8') as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ Listo! Base de datos: {DATABASE_PATH}")
    print("   Ejecuta: PYTHONPATH=src python -m autobots.dashboard.app para iniciar el panel")


if __name__ == '__main__':
    main()
