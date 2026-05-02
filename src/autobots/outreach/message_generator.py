"""
Generador de plantilla Excel con URLs de WhatsApp para contacto con negocios.
"""

import json
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill

from autobots.outreach.whatsapp_links import generate_wa_me_link
from autobots.utils.phone import normalize_paraguay_phone_digits


PROJECT_ROOT = Path(__file__).resolve().parents[3]

def limpiar_telefono(telefono):
    """Limpia el número de teléfono para formato WhatsApp."""
    return normalize_paraguay_phone_digits(telefono)


def generar_url_whatsapp(telefono, nombre_negocio):
    """Genera URL de WhatsApp con mensaje personalizado."""
    mensaje = f"Buenas! Soy Nicolás. Hablo con el responsable de {nombre_negocio}? Vi su local en Google Maps y vi que hay algo que puede hacer que mas clientes les encuentren. Puedo comentarles en unos 30 segundos?"
    
    return generate_wa_me_link(telefono, mensaje)


def generar_plantilla_excel(leads_file=None, output_file=None):
    """Genera archivo Excel con datos de contacto y URLs de WhatsApp."""
    
    # Cargar datos de leads
    leads_file = Path(leads_file) if leads_file else PROJECT_ROOT / "data" / "processed" / "leads.json"
    output_file = Path(output_file) if output_file else PROJECT_ROOT / "data" / "processed" / "plantilla_whatsapp_contacto.xlsx"
    
    with open(leads_file, 'r', encoding='utf-8') as f:
        leads = json.load(f)
    
    # Crear workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Contactos WhatsApp"
    
    # Encabezados
    headers = ['ID', 'Negocio', 'Teléfono Original', 'Teléfono WhatsApp', 'URL WhatsApp', 'Ciudad', 'Rating', 'Reviews', 'Estado']
    ws.append(headers)
    
    # Estilo para encabezados
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    
    for col in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center', vertical='center')
    
    # Agregar datos
    row_num = 2
    leads_con_telefono = 0
    leads_sin_telefono = 0
    
    for lead in leads:
        telefono_original = lead.get('telefono', '')
        telefono_limpio = limpiar_telefono(telefono_original)
        
        if telefono_limpio:
            leads_con_telefono += 1
            nombre = lead.get('nombre', '')
            url_whatsapp = generar_url_whatsapp(telefono_limpio, nombre)
            
            # Agregar fila
            ws.cell(row=row_num, column=1, value=lead.get('id'))
            ws.cell(row=row_num, column=2, value=nombre)
            ws.cell(row=row_num, column=3, value=telefono_original)
            ws.cell(row=row_num, column=4, value=telefono_limpio)
            
            # Crear hipervínculo para la URL de WhatsApp
            cell_url = ws.cell(row=row_num, column=5, value=url_whatsapp)
            cell_url.hyperlink = url_whatsapp
            cell_url.font = Font(color="0563C1", underline="single")
            
            ws.cell(row=row_num, column=6, value=lead.get('ciudad'))
            ws.cell(row=row_num, column=7, value=lead.get('rating'))
            ws.cell(row=row_num, column=8, value=lead.get('reviews'))
            ws.cell(row=row_num, column=9, value=lead.get('estado', 'pendiente'))
            
            row_num += 1
        else:
            leads_sin_telefono += 1
    
    # Ajustar ancho de columnas
    column_widths = {
        'A': 8,   # ID
        'B': 40,  # Negocio
        'C': 18,  # Teléfono Original
        'D': 18,  # Teléfono WhatsApp
        'E': 80,  # URL WhatsApp
        'F': 15,  # Ciudad
        'G': 10,  # Rating
        'H': 10,  # Reviews
        'I': 12   # Estado
    }
    
    for col, width in column_widths.items():
        ws.column_dimensions[col].width = width
    
    # Congelar primera fila
    ws.freeze_panes = 'A2'
    
    # Guardar archivo
    output_file.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_file)
    
    print(f"✅ Plantilla generada exitosamente: {output_file}")
    print(f"📊 Total de leads con teléfono: {leads_con_telefono}")
    print(f"⚠️  Total de leads sin teléfono: {leads_sin_telefono}")
    print(f"📱 Total de URLs de WhatsApp generadas: {leads_con_telefono}")
    

if __name__ == "__main__":
    generar_plantilla_excel()
