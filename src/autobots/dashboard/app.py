#!/usr/bin/env python3
"""
Panel de Ventas v2 - Diseño Cálido
Sin login, con filtros por categoría y score de compra
"""

import sys
import json
import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template_string, request, jsonify

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

app = Flask(__name__)

try:
    from editor import editor_bp, init_db as init_editor_db
except ImportError:
    editor_bp = None

    def init_editor_db():
        return None
else:
    app.register_blueprint(editor_bp)

# Build absolute path to database
DATABASE_PATH = PROJECT_ROOT / 'data' / 'processed' / 'ventas_v2.db'
GENERATED_SITES_DIR = PROJECT_ROOT / 'generated_sites'

# ============================================
# CATEGORÍAS GENERALES
# ============================================
CATEGORIA_GENERAL = {
    # Gastronomía
    'Restaurante': 'Gastronomía',
    'Bar': 'Gastronomía',
    'Bar restaurante': 'Gastronomía',
    'Bar con música en directo': 'Gastronomía',
    'Bar deportivo': 'Gastronomía',
    'Cafetería': 'Gastronomía',
    'Buffet libre': 'Gastronomía',
    'Cervecería artesanal': 'Gastronomía',
    'Chocolatería': 'Gastronomía',
    'Panadería': 'Gastronomía',
    'Pastelería': 'Gastronomía',
    'Heladería': 'Gastronomía',
    'Pizzería': 'Gastronomía',
    'Tostadores de café': 'Gastronomía',
    'Comida rápida': 'Gastronomía',
    'Restaurante asiático': 'Gastronomía',
    'Restaurante italiano': 'Gastronomía',
    'Restaurante japonés': 'Gastronomía',
    'Restaurante mexicano': 'Gastronomía',
    'Restaurante vegano': 'Gastronomía',
    'Sushi': 'Gastronomía',
    'Steakhouse': 'Gastronomía',
    'Hamburguesería': 'Gastronomía',
    'Asador': 'Gastronomía',
    'Parrilla': 'Gastronomía',
    
    # Belleza y Bienestar
    'Spa': 'Belleza y Bienestar',
    'Centro de estética': 'Belleza y Bienestar',
    'Academia de estética': 'Belleza y Bienestar',
    'Esteticista': 'Belleza y Bienestar',
    'Esteticista facial': 'Belleza y Bienestar',
    'Barbería': 'Belleza y Bienestar',
    'Peluquería': 'Belleza y Bienestar',
    'Cuidado del cabello': 'Belleza y Bienestar',
    'Depilación con cera': 'Belleza y Bienestar',
    'Centro de yoga': 'Belleza y Bienestar',
    'Centro de pilates': 'Belleza y Bienestar',
    'Balneario': 'Belleza y Bienestar',
    'Gimnasio': 'Belleza y Bienestar',
    'Centro deportivo': 'Belleza y Bienestar',
    'Salón de belleza': 'Belleza y Bienestar',
    'Salón de uñas': 'Belleza y Bienestar',
    
    # Salud
    'Clínica dental': 'Salud',
    'Dentista': 'Salud',
    'Farmacia': 'Salud',
    'Farmacia veterinaria': 'Salud',
    'Veterinaria': 'Salud',
    'Óptica': 'Salud',
    'Clínica': 'Salud',
    'Hospital': 'Salud',
    'Laboratorio': 'Salud',
    'Consultorio': 'Salud',
    
    # Automotriz
    'Taller mecánico': 'Automotriz',
    'Concesionario de automóviles': 'Automotriz',
    'Concesionario Toyota': 'Automotriz',
    'Lavadero de autos': 'Automotriz',
    'Agencia de alquiler de coches': 'Automotriz',
    'Repuestos': 'Automotriz',
    'Autopartes': 'Automotriz',
    
    # Comercio y Tiendas
    'Comercio': 'Comercio',
    'Tienda': 'Comercio',
    'Ferretería': 'Comercio',
    'Floristería': 'Comercio',
    'Floristería mayorista': 'Comercio',
    'Joyería': 'Comercio',
    'Óptica': 'Comercio',
    'Tienda de ropa': 'Comercio',
    'Tienda de zapatos': 'Comercio',
    'Tienda de electrónica': 'Comercio',
    'Supermercado': 'Comercio',
    'Minimarket': 'Comercio',
    
    # Servicios Profesionales
    'Agencia de publicidad': 'Servicios Profesionales',
    'Diseñador gráfico': 'Servicios Profesionales',
    'Fotógrafo': 'Servicios Profesionales',
    'Fotógrafo de bodas': 'Servicios Profesionales',
    'Estudio de fotografía': 'Servicios Profesionales',
    'Estudio de grabación': 'Servicios Profesionales',
    'Agente de aduanas': 'Servicios Profesionales',
    'Asesor en comercio internacional': 'Servicios Profesionales',
    'Empresa de importación y exportación': 'Servicios Profesionales',
    'Abogado': 'Servicios Profesionales',
    'Contador': 'Servicios Profesionales',
    'Consultoría': 'Servicios Profesionales',
    
    # Construcción e Inmobiliaria
    'Empresa de construcción': 'Construcción',
    'Inmobiliaria': 'Construcción',
    'Arquitecto': 'Construcción',
    'Constructora': 'Construcción',
    
    # Tecnología y Reparaciones
    'Establecimiento de reparación de artículos electrónicos': 'Tecnología',
    'Informática': 'Tecnología',
    'Reparación de celulares': 'Tecnología',
    'Tienda de computadoras': 'Tecnología',
    
    # Educación y Deportes
    'Escuela de artes marciales': 'Educación y Deportes',
    'Academia': 'Educación y Deportes',
    'Colegio': 'Educación y Deportes',
    'Instituto': 'Educación y Deportes',
    'Gimnasio': 'Educación y Deportes',
    
    # Hotelería y Turismo
    'Complejo hotelero': 'Hotelería',
    'Hotel': 'Hotelería',
    'Hostal': 'Hotelería',
    'Resort': 'Hotelería',
    
    # Náutica
    'Compraventa de yates': 'Náutica',
    'Marina': 'Náutica',
    
    # Centro Comercial
    'Centro comercial': 'Centro Comercial',
}

def get_categoria_general(categoria):
    """Obtiene la categoría general de una categoría específica"""
    return CATEGORIA_GENERAL.get(categoria, 'Otros')

# ============================================
# API
# ============================================

def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@app.route('/')
def dashboard():
    return render_template_string(DASHBOARD_HTML)


@app.route('/api/stats')
def api_stats():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM leads')
    total = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM leads WHERE estado = "pendiente"')
    pendientes = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM leads WHERE estado = "contactado"')
    contactados = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM leads WHERE estado = "interesado"')
    interesados = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM leads WHERE estado = "demo"')
    demos = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM leads WHERE estado = "cerrado"')
    cerrados = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM leads WHERE estado = "rechazado"')
    rechazados = cursor.fetchone()[0]
    
    cursor.execute('SELECT MAX(lote) FROM leads')
    total_lotes = cursor.fetchone()[0] or 0
    
    cursor.execute('SELECT AVG(score_compra) FROM leads')
    score_promedio = cursor.fetchone()[0] or 0
    
    cursor.execute('SELECT COUNT(*) FROM leads WHERE instagram IS NOT NULL')
    con_instagram = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(*) FROM leads WHERE tiene_web = 0')
    sin_website = cursor.fetchone()[0]
    
    conn.close()
    
    return jsonify({
        'total': total,
        'pendientes': pendientes,
        'contactados': contactados,
        'interesados': interesados,
        'demos': demos,
        'cerrados': cerrados,
        'rechazados': rechazados,
        'total_lotes': total_lotes,
        'score_promedio': round(score_promedio, 1),
        'con_instagram': con_instagram,
        'sin_website': sin_website
    })


@app.route('/api/categorias')
def api_categorias():
    """Retorna las categorías generales disponibles"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT DISTINCT categoria FROM leads')
    categorias_raw = [row['categoria'] for row in cursor.fetchall()]
    conn.close()
    
    # Convertir a categorías generales y eliminar duplicados
    categorias_generales = sorted(set(get_categoria_general(cat) for cat in categorias_raw))
    return jsonify(categorias_generales)


@app.route('/api/lotes')
def api_lotes():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT lote, fecha_asignacion, 
               COUNT(*) as total,
               AVG(score_compra) as score_promedio,
               SUM(CASE WHEN estado = 'pendiente' THEN 1 ELSE 0 END) as pendientes,
               SUM(CASE WHEN estado = 'contactado' THEN 1 ELSE 0 END) as contactados,
               SUM(CASE WHEN estado = 'interesado' THEN 1 ELSE 0 END) as interesados,
               SUM(CASE WHEN estado = 'cerrado' THEN 1 ELSE 0 END) as cerrados,
               SUM(CASE WHEN instagram IS NOT NULL THEN 1 ELSE 0 END) as con_instagram,
               SUM(CASE WHEN tiene_web = 0 THEN 1 ELSE 0 END) as sin_web
        FROM leads
        GROUP BY lote
        ORDER BY lote
    ''')
    
    lotes = []
    for row in cursor.fetchall():
        lotes.append({
            'lote': row['lote'],
            'fecha': row['fecha_asignacion'],
            'total': row['total'],
            'score_promedio': round(row['score_promedio'], 1),
            'pendientes': row['pendientes'],
            'contactados': row['contactados'],
            'interesados': row['interesados'],
            'cerrados': row['cerrados'],
            'con_instagram': row['con_instagram'],
            'sin_web': row['sin_web']
        })
    
    conn.close()
    return jsonify(lotes)


@app.route('/api/leads')
def api_leads():
    lote = request.args.get('lote', type=int)
    estado = request.args.get('estado')
    categoria_general = request.args.get('categoria')
    orden = request.args.get('orden', 'score')
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Primero obtenemos todos los leads
    query = 'SELECT * FROM leads WHERE 1=1'
    params = []
    
    if lote:
        query += ' AND lote = ?'
        params.append(lote)
    
    if estado:
        query += ' AND estado = ?'
        params.append(estado)
    
    if orden == 'score':
        query += ' ORDER BY score_compra DESC'
    elif orden == 'reviews':
        query += ' ORDER BY reviews DESC'
    else:
        query += ' ORDER BY nombre'
    
    cursor.execute(query, params)
    
    leads = []
    for row in cursor.fetchall():
        categoria_original = row['categoria']
        cat_general = get_categoria_general(categoria_original)
        
        # Filtrar por categoría general si se especificó
        if categoria_general and cat_general != categoria_general:
            continue
            
        leads.append({
            'id': row['id'],
            'nombre': row['nombre'],
            'categoria': categoria_original,
            'categoria_general': cat_general,
            'telefono': row['telefono'],
            'instagram': row['instagram'],
            'facebook': row['facebook'],
            'website_actual': row['website_actual'],
            'tiene_web': bool(row['tiene_web']),
            'direccion': row['direccion'],
            'ciudad': row['ciudad'],
            'barrio': row['barrio'],
            'google_maps': row['google_maps'],
            'rating': row['rating'],
            'reviews': row['reviews'],
            'fotos': row['fotos'],
            'score_compra': row['score_compra'],
            'score_detalles': row['score_detalles'],
            'estado': row['estado'],
            'lote': row['lote'],
            'notas': row['notas'],
            'fecha_contacto': row['fecha_contacto'],
            'resultado_llamada': row['resultado_llamada']
        })
    
    conn.close()
    return jsonify(leads)


@app.route('/api/lead/<int:lead_id>', methods=['PUT'])
def api_update_lead(lead_id):
    data = request.json
    conn = get_db()
    cursor = conn.cursor()
    
    updates = []
    params = []
    
    if 'estado' in data:
        updates.append('estado = ?')
        params.append(data['estado'])
        if data['estado'] != 'pendiente':
            updates.append('fecha_contacto = ?')
            params.append(datetime.now().isoformat())
    
    if 'notas' in data:
        updates.append('notas = ?')
        params.append(data['notas'])
    
    if 'resultado_llamada' in data:
        updates.append('resultado_llamada = ?')
        params.append(data['resultado_llamada'])
    
    if updates:
        updates.append('updated_at = ?')
        params.append(datetime.now().isoformat())
        params.append(lead_id)
        
        cursor.execute(f'UPDATE leads SET {", ".join(updates)} WHERE id = ?', params)
        conn.commit()
    
    conn.close()
    return jsonify({'success': True})


# ============================================
# EDIT LINK MANAGEMENT
# ============================================

def _slugify(text):
    """Convert text to URL-friendly slug (matches builder.py behavior - preserves accents)."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text).strip('-')
    return text[:50]


def _normalize_for_compare(text):
    """Strip accents for fuzzy comparison."""
    text = unicodedata.normalize('NFD', text.lower())
    text = re.sub(r'[\u0300-\u036f]', '', text)  # remove combining diacritics
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text).strip('-')
    return text


def _find_site_folder(lead_name):
    """Find the generated site folder matching a lead name."""
    sites_dir = GENERATED_SITES_DIR
    if not sites_dir.exists():
        return None
    lead_norm = _normalize_for_compare(lead_name)
    lead_slug = _slugify(lead_name)
    if not lead_norm:
        return None
    for folder_path in sorted(sites_dir.iterdir()):
        if folder_path.is_dir():
            folder = folder_path.name
            # Folder format: NNNN-slug-name
            folder_slug = '-'.join(folder.split('-')[1:])
            folder_norm = _normalize_for_compare(folder_slug)
            # Match by normalized (accent-stripped) comparison
            if (folder_norm == lead_norm
                or lead_norm in folder_norm
                or folder_norm.startswith(lead_norm[:20])
                or folder_slug == lead_slug):
                return folder
    return None


@app.route('/api/lead/<int:lead_id>/generate-edit-link', methods=['POST'])
def generate_edit_link(lead_id):
    """Generate an edit token for a lead's generated site."""
    if editor_bp is None:
        return jsonify({'error': 'Editor module is not available in this repo'}), 501

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT nombre, categoria FROM leads WHERE id = ?', (lead_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return jsonify({'error': 'Lead no encontrado'}), 404

    nombre = row['nombre']
    site_folder = _find_site_folder(nombre)

    if not site_folder:
        return jsonify({'error': f'No se encontró sitio generado para "{nombre}"'}), 404

    try:
        from editor.db import create_token, init_db
        init_db()
        token = create_token(
            site_folder=site_folder,
            business_name=nombre,
            business_index=lead_id,
        )
        return jsonify({
            'token': token,
            'edit_url': f'/editor/{token}',
            'site_folder': site_folder,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================
# HTML TEMPLATE - DISEÑO CÁLIDO
# ============================================

DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Panel de Ventas - WebConstructor</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    fontFamily: { sans: ['Inter', 'sans-serif'] },
                    colors: {
                        cream: { 50: '#FEFDFB', 100: '#FBF9F5', 200: '#F5F0E8' },
                        warm: { 500: '#78716C', 600: '#57534E', 700: '#44403C', 800: '#292524' }
                    }
                }
            }
        }
    </script>
    <style>
        body { font-family: 'Inter', sans-serif; }
        [x-cloak] { display: none !important; }
        .estado-pendiente { background: #f3f4f6; color: #374151; }
        .estado-contactado { background: #dbeafe; color: #1e40af; }
        .estado-interesado { background: #dcfce7; color: #166534; }
        .estado-demo { background: #f3e8ff; color: #7c3aed; }
        .estado-cerrado { background: #bbf7d0; color: #15803d; }
        .estado-rechazado { background: #fee2e2; color: #dc2626; }
        .animate-scale-in { animation: scaleIn 0.2s ease-out; }
        @keyframes scaleIn { from { opacity: 0; transform: scale(0.95); } to { opacity: 1; transform: scale(1); } }
    </style>
</head>
<body class="bg-cream-100 text-warm-800 min-h-screen" x-data="salesApp()">
    
    <!-- Header -->
    <header class="bg-white border-b border-cream-200 px-6 py-4 shadow-sm">
        <div class="max-w-7xl mx-auto flex justify-between items-center">
            <div>
                <h1 class="text-2xl font-bold text-warm-800">📊 Panel de Ventas</h1>
                <p class="text-warm-500 text-sm">WebConstructor.dev - Gestión de Leads</p>
            </div>
            <div class="text-warm-500" x-text="new Date().toLocaleDateString('es-PY', {weekday: 'long', day: 'numeric', month: 'long'})"></div>
        </div>
    </header>
    
    <div class="max-w-7xl mx-auto p-6">
        
        <!-- Stats Cards -->
        <div class="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4 mb-6">
            <div class="bg-white rounded-xl p-4 shadow-sm border border-cream-200">
                <div class="text-3xl font-bold text-warm-800" x-text="stats.total || 0"></div>
                <div class="text-warm-500 text-sm">Total</div>
            </div>
            <div class="bg-gray-50 rounded-xl p-4 shadow-sm border border-gray-200">
                <div class="text-3xl font-bold text-gray-600" x-text="stats.pendientes || 0"></div>
                <div class="text-gray-500 text-sm">Pendientes</div>
            </div>
            <div class="bg-blue-50 rounded-xl p-4 shadow-sm border border-blue-200">
                <div class="text-3xl font-bold text-blue-600" x-text="stats.contactados || 0"></div>
                <div class="text-blue-500 text-sm">Contactados</div>
            </div>
            <div class="bg-green-50 rounded-xl p-4 shadow-sm border border-green-200">
                <div class="text-3xl font-bold text-green-600" x-text="stats.interesados || 0"></div>
                <div class="text-green-500 text-sm">Interesados</div>
            </div>
            <div class="bg-purple-50 rounded-xl p-4 shadow-sm border border-purple-200">
                <div class="text-3xl font-bold text-purple-600" x-text="stats.demos || 0"></div>
                <div class="text-purple-500 text-sm">Demos</div>
            </div>
            <div class="bg-emerald-50 rounded-xl p-4 shadow-sm border border-emerald-200">
                <div class="text-3xl font-bold text-emerald-600" x-text="stats.cerrados || 0"></div>
                <div class="text-emerald-500 text-sm">🎉 Cerrados</div>
            </div>
            <div class="bg-orange-50 rounded-xl p-4 shadow-sm border border-orange-200">
                <div class="text-3xl font-bold text-orange-600" x-text="stats.sin_website || 0"></div>
                <div class="text-orange-500 text-sm">🎯 Sin Web</div>
            </div>
        </div>
        
        <!-- Main Content -->
        <div class="grid lg:grid-cols-4 gap-6">
            
            <!-- Lotes Sidebar -->
            <div class="lg:col-span-1 bg-white rounded-xl p-4 shadow-sm border border-cream-200 max-h-[75vh] overflow-y-auto">
                <h2 class="text-lg font-semibold mb-4 text-warm-700">📦 Lotes por Score</h2>
                <div class="space-y-2">
                    <div @click="selectedLote = null; loadLeads()"
                         :class="!selectedLote ? 'bg-warm-800 text-white' : 'bg-cream-100 hover:bg-cream-200 text-warm-700'"
                         class="rounded-lg p-3 cursor-pointer transition font-medium">
                        Todos los leads
                    </div>
                    <template x-for="lote in lotes" :key="lote.lote">
                        <div @click="selectLote(lote.lote)"
                             :class="selectedLote === lote.lote ? 'bg-warm-800 text-white' : 'bg-cream-50 hover:bg-cream-200 text-warm-700'"
                             class="rounded-lg p-3 cursor-pointer transition border border-cream-200">
                            <div class="flex justify-between items-center">
                                <span class="font-medium">Lote <span x-text="lote.lote"></span></span>
                                <span class="text-xs px-2 py-1 rounded-full font-semibold"
                                      :class="lote.score_promedio >= 70 ? 'bg-green-100 text-green-700' : lote.score_promedio >= 50 ? 'bg-yellow-100 text-yellow-700' : 'bg-red-100 text-red-700'">
                                    <span x-text="lote.score_promedio"></span>
                                </span>
                            </div>
                            <div class="text-xs text-warm-500 mt-1">
                                <span x-text="lote.pendientes"></span>/<span x-text="lote.total"></span> pendientes · 
                                <span x-text="lote.con_instagram"></span> IG
                            </div>
                        </div>
                    </template>
                </div>
            </div>
            
            <!-- Leads List -->
            <div class="lg:col-span-3 bg-white rounded-xl p-4 shadow-sm border border-cream-200">
                
                <!-- Filtros -->
                <div class="flex flex-wrap gap-3 mb-4 pb-4 border-b border-cream-200">
                    <select x-model="filtroCategoria" @change="loadLeads()" 
                            class="bg-cream-50 border border-cream-200 rounded-lg px-3 py-2 text-sm text-warm-700 focus:ring-2 focus:ring-warm-500">
                        <option value="">📁 Todas las categorías</option>
                        <template x-for="cat in categorias" :key="cat">
                            <option :value="cat" x-text="cat"></option>
                        </template>
                    </select>
                    <select x-model="filtroEstado" @change="loadLeads()" 
                            class="bg-cream-50 border border-cream-200 rounded-lg px-3 py-2 text-sm text-warm-700 focus:ring-2 focus:ring-warm-500">
                        <option value="">📋 Todos los estados</option>
                        <option value="pendiente">⏳ Pendiente</option>
                        <option value="contactado">📞 Contactado</option>
                        <option value="interesado">✅ Interesado</option>
                        <option value="demo">🎬 Demo</option>
                        <option value="cerrado">🎉 Cerrado</option>
                        <option value="rechazado">❌ Rechazado</option>
                    </select>
                    <select x-model="orden" @change="loadLeads()"
                            class="bg-cream-50 border border-cream-200 rounded-lg px-3 py-2 text-sm text-warm-700 focus:ring-2 focus:ring-warm-500">
                        <option value="score">📊 Por Score</option>
                        <option value="reviews">💬 Por Reviews</option>
                        <option value="nombre">🔤 Por Nombre</option>
                    </select>
                    <div class="ml-auto text-sm text-warm-500">
                        <span x-text="leads.length"></span> leads
                    </div>
                </div>
                
                <!-- Leads Grid -->
                <div class="space-y-3 max-h-[65vh] overflow-y-auto">
                    <template x-for="lead in leads" :key="lead.id">
                        <div class="bg-cream-50 rounded-xl p-4 hover:bg-cream-100 transition border border-cream-200">
                            <div class="flex justify-between items-start gap-4">
                                <!-- Info Principal -->
                                <div class="flex-1">
                                    <div class="flex items-center gap-2 mb-1">
                                        <h3 class="font-semibold text-lg text-warm-800" x-text="lead.nombre"></h3>
                                        <span class="text-xs px-2 py-0.5 rounded-full font-medium"
                                              :class="'estado-' + lead.estado" x-text="lead.estado"></span>
                                    </div>
                                    <div class="text-sm text-warm-500 mb-2">
                                        <span class="bg-warm-100 text-warm-700 px-2 py-0.5 rounded text-xs font-medium" x-text="lead.categoria_general"></span>
                                        <span class="text-warm-400 mx-1">›</span>
                                        <span class="text-warm-600" x-text="lead.categoria"></span> · 
                                        <span x-text="lead.barrio || lead.ciudad"></span>
                                    </div>
                                    
                                    <!-- Métricas -->
                                    <div class="flex items-center gap-4 text-sm mb-3">
                                        <span class="text-amber-600">
                                            ⭐ <span x-text="lead.rating"></span>
                                        </span>
                                        <span class="text-blue-600">
                                            💬 <span x-text="lead.reviews"></span>
                                        </span>
                                        <span class="font-semibold"
                                              :class="lead.score_compra >= 70 ? 'text-green-600' : lead.score_compra >= 50 ? 'text-amber-600' : 'text-red-600'">
                                            📊 <span x-text="lead.score_compra"></span>/100
                                        </span>
                                        <span x-show="!lead.tiene_web" class="text-orange-600 font-medium">
                                            🎯 Sin web
                                        </span>
                                    </div>
                                    
                                    <!-- Score Bar -->
                                    <div class="w-full bg-cream-200 rounded-full h-2 mb-2">
                                        <div class="h-2 rounded-full transition-all"
                                             :style="'width: ' + lead.score_compra + '%'"
                                             :class="lead.score_compra >= 70 ? 'bg-green-500' : lead.score_compra >= 50 ? 'bg-amber-500' : 'bg-red-500'">
                                        </div>
                                    </div>
                                </div>
                                
                                <!-- Contacto -->
                                <div class="text-right space-y-2">
                                    <a :href="'tel:' + lead.telefono" 
                                       class="block bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg text-sm font-semibold transition shadow-sm">
                                        📞 <span x-text="lead.telefono"></span>
                                    </a>
                                    <div class="flex gap-2 justify-end">
                                        <a x-show="lead.instagram" :href="lead.instagram" target="_blank"
                                           class="bg-gradient-to-r from-purple-500 to-pink-500 hover:from-purple-600 hover:to-pink-600 text-white p-2 rounded-lg transition shadow-sm">
                                            <i class="fab fa-instagram"></i>
                                        </a>
                                        <a x-show="lead.facebook" :href="lead.facebook" target="_blank"
                                           class="bg-blue-600 hover:bg-blue-700 text-white p-2 rounded-lg transition shadow-sm">
                                            <i class="fab fa-facebook"></i>
                                        </a>
                                        <a :href="lead.google_maps" target="_blank"
                                           class="bg-warm-600 hover:bg-warm-700 text-white p-2 rounded-lg transition shadow-sm">
                                            <i class="fas fa-map-marker-alt"></i>
                                        </a>
                                    </div>
                                </div>
                            </div>
                            
                            <!-- Acciones -->
                            <div class="flex flex-wrap gap-2 mt-3 pt-3 border-t border-cream-200">
                                <button @click="updateEstado(lead.id, 'contactado')"
                                        class="text-xs bg-blue-100 hover:bg-blue-200 text-blue-700 px-3 py-1.5 rounded-lg transition font-medium">
                                    📞 Contactado
                                </button>
                                <button @click="updateEstado(lead.id, 'interesado')"
                                        class="text-xs bg-green-100 hover:bg-green-200 text-green-700 px-3 py-1.5 rounded-lg transition font-medium">
                                    ✅ Interesado
                                </button>
                                <button @click="updateEstado(lead.id, 'demo')"
                                        class="text-xs bg-purple-100 hover:bg-purple-200 text-purple-700 px-3 py-1.5 rounded-lg transition font-medium">
                                    🎬 Demo
                                </button>
                                <button @click="updateEstado(lead.id, 'cerrado')"
                                        class="text-xs bg-emerald-100 hover:bg-emerald-200 text-emerald-700 px-3 py-1.5 rounded-lg transition font-medium">
                                    🎉 Cerrado
                                </button>
                                <button @click="updateEstado(lead.id, 'rechazado')"
                                        class="text-xs bg-red-100 hover:bg-red-200 text-red-700 px-3 py-1.5 rounded-lg transition font-medium">
                                    ❌ No
                                </button>
                                <button @click="updateEstado(lead.id, 'pendiente')"
                                        class="text-xs bg-gray-100 hover:bg-gray-200 text-gray-700 px-3 py-1.5 rounded-lg transition font-medium">
                                    ↩️ Reset
                                </button>
                                <button @click="openNotas(lead)"
                                        class="text-xs bg-amber-100 hover:bg-amber-200 text-amber-700 px-3 py-1.5 rounded-lg transition font-medium ml-auto">
                                    📝 Notas
                                </button>
                                <button @click="generateEditLink(lead)"
                                        :disabled="editLinkLoadingId === lead.id"
                                        class="text-xs bg-indigo-100 hover:bg-indigo-200 text-indigo-700 px-3 py-1.5 rounded-lg transition font-medium disabled:opacity-50">
                                    <i class="fas" :class="editLinkLoadingId === lead.id ? 'fa-spinner fa-spin' : 'fa-link'"></i>
                                    Edit Link
                                </button>
                            </div>

                            <!-- Notas existentes -->
                            <div x-show="lead.notas" class="mt-2 text-sm text-warm-600 bg-amber-50 rounded-lg p-2 border border-amber-200">
                                📝 <span x-text="lead.notas"></span>
                            </div>
                        </div>
                    </template>
                    
                    <div x-show="leads.length === 0" class="text-center py-12 text-warm-500">
                        No hay leads con estos filtros
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Modal Notas -->
    <div x-show="showNotasModal" x-cloak
         class="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
        <div class="bg-white rounded-2xl p-6 w-full max-w-lg shadow-xl border border-cream-200">
            <h3 class="text-xl font-bold mb-4 text-warm-800">📝 Notas para <span x-text="currentLead?.nombre"></span></h3>
            <textarea x-model="notasTexto" rows="4"
                      class="w-full bg-cream-50 border border-cream-200 rounded-lg p-3 text-warm-800 mb-4 focus:outline-none focus:ring-2 focus:ring-warm-500"
                      placeholder="Escribe tus notas aquí..."></textarea>
            <div class="flex justify-end gap-2">
                <button @click="showNotasModal = false" class="px-4 py-2 bg-cream-200 hover:bg-cream-300 text-warm-700 rounded-lg transition">Cancelar</button>
                <button @click="guardarNotas()" class="px-4 py-2 bg-warm-800 hover:bg-warm-700 text-white rounded-lg transition">Guardar</button>
            </div>
        </div>
    </div>

    <!-- Modal Edit Link -->
    <div x-show="showEditLinkModal" x-cloak
         class="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
         @click.self="showEditLinkModal = false">
        <div class="bg-white rounded-2xl p-6 w-full max-w-lg shadow-xl border border-indigo-200 animate-scale-in">
            <!-- Success state -->
            <div x-show="editLinkData.url">
                <div class="text-center mb-5">
                    <div class="w-16 h-16 mx-auto mb-3 rounded-full bg-indigo-100 flex items-center justify-center">
                        <i class="fas fa-link text-indigo-600 text-2xl"></i>
                    </div>
                    <h3 class="text-xl font-bold text-warm-800">Link de edición listo</h3>
                    <p class="text-warm-500 text-sm mt-1">Para: <strong x-text="editLinkData.nombre"></strong></p>
                </div>

                <div class="bg-indigo-50 border border-indigo-200 rounded-xl p-4 mb-4">
                    <label class="text-xs font-semibold text-indigo-600 block mb-2">URL del editor:</label>
                    <div class="flex items-center gap-2">
                        <input type="text" x-ref="editLinkInput" :value="editLinkData.fullUrl" readonly
                               class="flex-1 bg-white border border-indigo-300 rounded-lg px-3 py-2.5 text-sm font-mono text-indigo-800 focus:outline-none"
                               @click="$event.target.select()">
                        <button @click="copyEditLink()"
                                class="px-4 py-2.5 rounded-lg font-semibold text-sm transition"
                                :class="editLinkData.copied ? 'bg-green-600 text-white' : 'bg-indigo-600 hover:bg-indigo-700 text-white'">
                            <span x-show="!editLinkData.copied"><i class="fas fa-copy mr-1"></i> Copiar</span>
                            <span x-show="editLinkData.copied"><i class="fas fa-check mr-1"></i> Copiado!</span>
                        </button>
                    </div>
                </div>

                <div x-show="editLinkData.siteFolder" class="text-xs text-warm-500 mb-4">
                    <i class="fas fa-folder mr-1"></i> Sitio: <span x-text="editLinkData.siteFolder"></span>
                </div>

                <div class="flex justify-end gap-2">
                    <button @click="showEditLinkModal = false"
                            class="px-4 py-2 bg-cream-200 hover:bg-cream-300 text-warm-700 rounded-lg transition">
                        Cerrar
                    </button>
                    <a :href="editLinkData.url" target="_blank"
                       class="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg transition inline-flex items-center gap-2">
                        <i class="fas fa-external-link-alt"></i> Abrir editor
                    </a>
                </div>
            </div>

            <!-- Error state -->
            <div x-show="editLinkData.error">
                <div class="text-center mb-5">
                    <div class="w-16 h-16 mx-auto mb-3 rounded-full bg-red-100 flex items-center justify-center">
                        <i class="fas fa-exclamation-triangle text-red-500 text-2xl"></i>
                    </div>
                    <h3 class="text-xl font-bold text-warm-800">No se pudo generar el link</h3>
                    <p class="text-red-600 text-sm mt-2" x-text="editLinkData.error"></p>
                </div>
                <div class="flex justify-end">
                    <button @click="showEditLinkModal = false"
                            class="px-4 py-2 bg-cream-200 hover:bg-cream-300 text-warm-700 rounded-lg transition">
                        Cerrar
                    </button>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        function salesApp() {
            return {
                stats: {},
                lotes: [],
                leads: [],
                categorias: [],
                selectedLote: null,
                filtroEstado: '',
                filtroCategoria: '',
                orden: 'score',
                showNotasModal: false,
                currentLead: null,
                notasTexto: '',
                showEditLinkModal: false,
                editLinkLoadingId: null,
                editLinkData: { url: '', fullUrl: '', nombre: '', siteFolder: '', copied: false, error: '' },
                
                init() {
                    this.loadStats();
                    this.loadLotes();
                    this.loadCategorias();
                    this.loadLeads();
                },
                
                async loadStats() {
                    const res = await fetch('/api/stats');
                    this.stats = await res.json();
                },
                
                async loadLotes() {
                    const res = await fetch('/api/lotes');
                    this.lotes = await res.json();
                },
                
                async loadCategorias() {
                    const res = await fetch('/api/categorias');
                    this.categorias = await res.json();
                },
                
                async loadLeads() {
                    let url = '/api/leads?orden=' + this.orden;
                    if (this.selectedLote) url += '&lote=' + this.selectedLote;
                    if (this.filtroEstado) url += '&estado=' + this.filtroEstado;
                    if (this.filtroCategoria) url += '&categoria=' + encodeURIComponent(this.filtroCategoria);
                    const res = await fetch(url);
                    this.leads = await res.json();
                },
                
                selectLote(lote) {
                    this.selectedLote = this.selectedLote === lote ? null : lote;
                    this.loadLeads();
                },
                
                async updateEstado(leadId, estado) {
                    await fetch('/api/lead/' + leadId, {
                        method: 'PUT',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({estado})
                    });
                    this.loadLeads();
                    this.loadStats();
                    this.loadLotes();
                },
                
                openNotas(lead) {
                    this.currentLead = lead;
                    this.notasTexto = lead.notas || '';
                    this.showNotasModal = true;
                },
                
                async guardarNotas() {
                    await fetch('/api/lead/' + this.currentLead.id, {
                        method: 'PUT',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({notas: this.notasTexto})
                    });
                    this.showNotasModal = false;
                    this.loadLeads();
                },

                async generateEditLink(lead) {
                    this.editLinkLoadingId = lead.id;
                    this.editLinkData = { url: '', fullUrl: '', nombre: lead.nombre, siteFolder: '', copied: false, error: '' };
                    try {
                        const res = await fetch('/api/lead/' + lead.id + '/generate-edit-link', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'}
                        });
                        if (!res.ok) {
                            const errData = await res.json().catch(() => ({}));
                            this.editLinkData.error = errData.error || 'Error del servidor (HTTP ' + res.status + ')';
                        } else {
                            const data = await res.json();
                            if (data.edit_url) {
                                this.editLinkData.url = data.edit_url;
                                this.editLinkData.fullUrl = window.location.origin + data.edit_url;
                                this.editLinkData.siteFolder = data.site_folder || '';
                            } else {
                                this.editLinkData.error = data.error || 'Error desconocido';
                            }
                        }
                    } catch (err) {
                        this.editLinkData.error = 'Error de conexión al servidor';
                    }
                    this.editLinkLoadingId = null;
                    this.showEditLinkModal = true;
                },

                copyEditLink() {
                    navigator.clipboard.writeText(this.editLinkData.fullUrl).then(() => {
                        this.editLinkData.copied = true;
                        setTimeout(() => { this.editLinkData.copied = false; }, 2000);
                    });
                }
            }
        }
    </script>
</body>
</html>
'''


if __name__ == '__main__':
    init_editor_db()
    print("🚀 Panel de Ventas v2 - Diseño Cálido")
    print("=" * 40)
    print("📍 URL: http://localhost:5002")
    print("=" * 40)
    app.run(host='0.0.0.0', port=5002, debug=True)
