# NODOS ADICIONALES PARA N8N
# Funcionalidades avanzadas: Notion CRM, Rate Limiting, Error Logging
# Copiar y pegar estos JSONs en n8n

---

## CONFIGURACIÓN PREVIA REQUERIDA EN NOTION

Antes de usar estos nodos, necesitás:

1. Crear una integración en Notion:
   - Ir a https://www.notion.so/my-integrations
   - Clic "New integration"
   - Nombre: "CRM Campaña WhatsApp"
   - Copiar el "Internal Integration Token" (empieza con `secret_`)

2. Crear una base de datos en Notion con estas columnas:
   - `Celular` (Title) — el número de teléfono
   - `Estado` (Select) — opciones: "nuevo", "interesado", "contactado", "inactivo"
   - `Historial` (Text) — JSON con el historial de conversación
   - `UltimoMensaje` (Date) — timestamp del último mensaje
   - `Resumen` (Text) — resumen de la conversación (esto estaria bueno si lo programo yo, algun text summarized que corra en local para poder ahorrar costos)
   - `ContadorMensajes` (Number) — para rate limiting
   - `UltimoReset` (Date) — para resetear el contador

3. Conectar la integración a la base de datos:
   - Abrir la base de datos en Notion
   - Clic en "..." → "Connect to" → seleccionar tu integración

4. Copiar el Database ID:
   - La URL de tu base de datos es: https://notion.so/TU_WORKSPACE/DATABASE_ID?v=...
   - El DATABASE_ID son los 32 caracteres antes del "?"

---

## NODO 1: BUSCAR CONTACTO EN NOTION (antes del AI Agent)

Este nodo busca si el contacto ya existe en Notion para cargar su historial.

### Configuración del nodo HTTP Request:

```json
{
  "parameters": {
    "method": "POST",
    "url": "https://api.notion.com/v1/databases/TU_DATABASE_ID/query",
    "sendHeaders": true,
    "headerParameters": {
      "parameters": [
        {
          "name": "Authorization",
          "value": "Bearer TU_NOTION_TOKEN"
        },
        {
          "name": "Notion-Version",
          "value": "2022-06-28"
        },
        {
          "name": "Content-Type",
          "value": "application/json"
        }
      ]
    },
    "sendBody": true,
    "specifyBody": "json",
    "jsonBody": "={\n  \"filter\": {\n    \"property\": \"Celular\",\n    \"title\": {\n      \"equals\": \"{{ $json.celular }}\"\n    }\n  }\n}"
  },
  "name": "Buscar en Notion",
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.2
}
```

**REEMPLAZAR:**
- `TU_DATABASE_ID` → ID de tu base de datos Notion (32 caracteres)
- `TU_NOTION_TOKEN` → Token que empieza con `secret_`

---

## NODO 2: CODE - PROCESAR HISTORIAL Y RATE LIMITING

Este nodo verifica rate limiting y prepara el historial para el AI Agent.
Ponerlo DESPUÉS de "Buscar en Notion" y ANTES del "IF Filtro".

### Código JavaScript completo:

```javascript
// =============================================================
// NODO CODE: PROCESAR HISTORIAL Y VERIFICAR RATE LIMITING
// Ubicación: después de "Buscar en Notion", antes de "IF Filtro"
// =============================================================

const celular = $('Set Fields').item.json.celular;
const mensaje = $('Set Fields').item.json.mensaje;
const notionResults = $input.first().json.results || [];

// Valores por defecto si el contacto no existe en Notion
let contactoExiste = false;
let historialPrevio = [];
let contadorMensajes = 0;
let ultimoReset = null;
let pageId = null;
let rateLimitExcedido = false;

// Si encontramos el contacto en Notion
if (notionResults.length > 0) {
  contactoExiste = true;
  const page = notionResults[0];
  pageId = page.id;
  
  // Cargar historial previo
  const historialJson = page.properties.Historial?.rich_text?.[0]?.plain_text || '[]';
  try {
    historialPrevio = JSON.parse(historialJson);
  } catch (e) {
    historialPrevio = [];
  }
  
  // Verificar rate limiting
  contadorMensajes = page.properties.ContadorMensajes?.number || 0;
  const ultimoResetStr = page.properties.UltimoReset?.date?.start;
  
  if (ultimoResetStr) {
    ultimoReset = new Date(ultimoResetStr);
    const ahora = new Date();
    const diffMinutos = (ahora - ultimoReset) / (1000 * 60);
    
    // Si pasaron más de 10 minutos, resetear contador
    if (diffMinutos > 10) {
      contadorMensajes = 1;
      ultimoReset = ahora;
    } else {
      contadorMensajes++;
      // Si excede 5 mensajes en 10 minutos → rate limit
      if (contadorMensajes > 5) {
        rateLimitExcedido = true;
      }
    }
  } else {
    // Primera vez que se registra
    contadorMensajes = 1;
    ultimoReset = new Date();
  }
} else {
  // Contacto nuevo
  contadorMensajes = 1;
  ultimoReset = new Date();
}

// Agregar mensaje actual al historial (para contexto)
historialPrevio.push({
  rol: 'usuario',
  mensaje: mensaje,
  timestamp: new Date().toISOString()
});

// Limitar historial a últimos 10 mensajes para no exceder tokens
const historialReciente = historialPrevio.slice(-10);

// Formatear historial como texto para el AI Agent
const historialTexto = historialReciente
  .map(h => `${h.rol === 'usuario' ? 'Usuario' : 'Asistente'}: ${h.mensaje}`)
  .join('\n');

return [{
  json: {
    // Datos originales
    celular: celular,
    mensaje: mensaje,
    fromMe: $('Set Fields').item.json.fromMe,
    isGroup: $('Set Fields').item.json.isGroup,
    sessionId: $('Set Fields').item.json.sessionId,
    
    // Datos de Notion
    contactoExiste: contactoExiste,
    notionPageId: pageId,
    historialPrevio: historialPrevio,
    historialTexto: historialTexto,
    
    // Rate limiting
    contadorMensajes: contadorMensajes,
    ultimoReset: ultimoReset ? ultimoReset.toISOString() : new Date().toISOString(),
    rateLimitExcedido: rateLimitExcedido
  }
}];
```

---

## NODO 3: IF - VERIFICAR RATE LIMIT

Agregar DESPUÉS del nodo Code anterior, ANTES del AI Agent.

### Configuración:

```json
{
  "parameters": {
    "conditions": {
      "options": {
        "caseSensitive": true,
        "leftValue": "",
        "typeValidation": "strict",
        "version": 2
      },
      "conditions": [
        {
          "id": "rate-limit-check",
          "leftValue": "={{ $json.rateLimitExcedido }}",
          "rightValue": true,
          "operator": {
            "type": "boolean",
            "operation": "equals"
          }
        }
      ],
      "combinator": "and"
    }
  },
  "name": "IF Rate Limit",
  "type": "n8n-nodes-base.if",
  "typeVersion": 2.1
}
```

**Conexiones:**
- TRUE → Nodo "Rate Limit Response" (respuesta automática + Telegram)
- FALSE → Continúa al AI Agent normal

---

## NODO 4: RATE LIMIT RESPONSE (rama TRUE del IF Rate Limit)

Cuando se excede el rate limit, envía respuesta automática y escala a Telegram.

### Nodo Code para respuesta de rate limit:

```javascript
// =============================================================
// NODO CODE: RESPUESTA RATE LIMIT
// Se ejecuta cuando el usuario manda más de 5 mensajes en 10 min
// =============================================================

const celular = $json.celular;
const mensaje = $json.mensaje;

return [{
  json: {
    celular: celular,
    mensaje: mensaje,
    respuesta_texto: "Recibí tus mensajes. Dame unos minutos y te respondo con calma. ¡Gracias por la paciencia!",
    delay_ms: 3000,
    should_escalate: true, // Siempre escalar a Telegram
    should_register: false,
    rate_limited: true
  }
}];
```

Después de este nodo, conectar al nodo "Wait" existente para que siga el flujo normal de envío.

---

## NODO 5: CREAR LEAD EN NOTION (después de IF Escalar, rama should_register=true)

Este nodo crea un nuevo lead cuando se detecta ##REGISTRAR_LEAD##.

### Primero, agregar un IF para verificar should_register:

```json
{
  "parameters": {
    "conditions": {
      "options": {
        "caseSensitive": true,
        "leftValue": "",
        "typeValidation": "strict",
        "version": 2
      },
      "conditions": [
        {
          "id": "should-register-check",
          "leftValue": "={{ $json.should_register }}",
          "rightValue": true,
          "operator": {
            "type": "boolean",
            "operation": "equals"
          }
        }
      ],
      "combinator": "and"
    }
  },
  "name": "IF Registrar Lead",
  "type": "n8n-nodes-base.if",
  "typeVersion": 2.1
}
```

### Nodo HTTP Request para crear página en Notion:

```json
{
  "parameters": {
    "method": "POST",
    "url": "https://api.notion.com/v1/pages",
    "sendHeaders": true,
    "headerParameters": {
      "parameters": [
        {
          "name": "Authorization",
          "value": "Bearer TU_NOTION_TOKEN"
        },
        {
          "name": "Notion-Version",
          "value": "2022-06-28"
        },
        {
          "name": "Content-Type",
          "value": "application/json"
        }
      ]
    },
    "sendBody": true,
    "specifyBody": "json",
    "jsonBody": "={\n  \"parent\": {\n    \"database_id\": \"TU_DATABASE_ID\"\n  },\n  \"properties\": {\n    \"Celular\": {\n      \"title\": [\n        {\n          \"text\": {\n            \"content\": \"{{ $json.celular }}\"\n          }\n        }\n      ]\n    },\n    \"Estado\": {\n      \"select\": {\n        \"name\": \"interesado\"\n      }\n    },\n    \"Resumen\": {\n      \"rich_text\": [\n        {\n          \"text\": {\n            \"content\": \"Lead detectado automáticamente. Último mensaje: {{ $json.mensaje.substring(0, 200) }}\"\n          }\n        }\n      ]\n    },\n    \"UltimoMensaje\": {\n      \"date\": {\n        \"start\": \"{{ $now.toISO() }}\"\n      }\n    },\n    \"ContadorMensajes\": {\n      \"number\": 1\n    },\n    \"Historial\": {\n      \"rich_text\": [\n        {\n          \"text\": {\n            \"content\": \"[]\"\n          }\n        }\n      ]\n    }\n  }\n}"
  },
  "name": "Crear Lead Notion",
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.2
}
```

**REEMPLAZAR:**
- `TU_DATABASE_ID` → ID de tu base de datos Notion
- `TU_NOTION_TOKEN` → Token de integración

---

## NODO 6: ACTUALIZAR HISTORIAL EN NOTION (al final del flujo)

Este nodo actualiza el historial después de cada conversación.
Ejecutar DESPUÉS de enviar la respuesta por Evolution API.

### Nodo Code para preparar actualización:

```javascript
// =============================================================
// NODO CODE: PREPARAR ACTUALIZACIÓN DE HISTORIAL
// Ejecutar después de enviar respuesta por Evolution API
// =============================================================

const celular = $('Set Fields').item.json.celular;
const mensaje = $('Set Fields').item.json.mensaje;
const respuesta = $('Code Delay').item.json.respuesta_texto;
const pageId = $('Procesar Historial').item.json.notionPageId;
const historialPrevio = $('Procesar Historial').item.json.historialPrevio || [];
const contadorMensajes = $('Procesar Historial').item.json.contadorMensajes;
const ultimoReset = $('Procesar Historial').item.json.ultimoReset;
const contactoExiste = $('Procesar Historial').item.json.contactoExiste;

// Agregar respuesta del asistente al historial
historialPrevio.push({
  rol: 'asistente',
  mensaje: respuesta,
  timestamp: new Date().toISOString()
});

// Limitar a últimos 20 intercambios para no exceder límite de Notion
const historialLimitado = historialPrevio.slice(-20);

return [{
  json: {
    celular: celular,
    pageId: pageId,
    contactoExiste: contactoExiste,
    historialJson: JSON.stringify(historialLimitado),
    contadorMensajes: contadorMensajes,
    ultimoReset: ultimoReset
  }
}];
```

### IF para verificar si contacto existe:

```json
{
  "parameters": {
    "conditions": {
      "options": {
        "caseSensitive": true,
        "leftValue": "",
        "typeValidation": "strict",
        "version": 2
      },
      "conditions": [
        {
          "id": "contacto-existe",
          "leftValue": "={{ $json.contactoExiste }}",
          "rightValue": true,
          "operator": {
            "type": "boolean",
            "operation": "equals"
          }
        }
      ],
      "combinator": "and"
    }
  },
  "name": "IF Contacto Existe",
  "type": "n8n-nodes-base.if",
  "typeVersion": 2.1
}
```

### Nodo HTTP Request PATCH para actualizar (rama TRUE):

```json
{
  "parameters": {
    "method": "PATCH",
    "url": "=https://api.notion.com/v1/pages/{{ $json.pageId }}",
    "sendHeaders": true,
    "headerParameters": {
      "parameters": [
        {
          "name": "Authorization",
          "value": "Bearer TU_NOTION_TOKEN"
        },
        {
          "name": "Notion-Version",
          "value": "2022-06-28"
        },
        {
          "name": "Content-Type",
          "value": "application/json"
        }
      ]
    },
    "sendBody": true,
    "specifyBody": "json",
    "jsonBody": "={\n  \"properties\": {\n    \"Historial\": {\n      \"rich_text\": [\n        {\n          \"text\": {\n            \"content\": {{ JSON.stringify($json.historialJson) }}\n          }\n        }\n      ]\n    },\n    \"UltimoMensaje\": {\n      \"date\": {\n        \"start\": \"{{ $now.toISO() }}\"\n      }\n    },\n    \"ContadorMensajes\": {\n      \"number\": {{ $json.contadorMensajes }}\n    },\n    \"UltimoReset\": {\n      \"date\": {\n        \"start\": \"{{ $json.ultimoReset }}\"\n      }\n    }\n  }\n}"
  },
  "name": "Actualizar Notion",
  "type": "n8n-nodes-base.httpRequest",
  "typeVersion": 4.2
}
```

### Nodo HTTP Request POST para crear nuevo contacto (rama FALSE):

Usar el mismo JSON del "Crear Lead Notion" pero con estado "nuevo" en lugar de "interesado".

---

## NODO 7: ERROR WORKFLOW - LOGGING DE ERRORES

Este es un workflow SEPARADO que se ejecuta cuando cualquier nodo falla.

### Crear nuevo workflow llamado "Error Handler":

```json
{
  "name": "Error Handler",
  "nodes": [
    {
      "parameters": {
        "conditions": {
          "options": {
            "caseSensitive": true,
            "leftValue": "",
            "typeValidation": "strict",
            "version": 2
          },
          "conditions": [
            {
              "id": "has-error",
              "leftValue": "={{ $json.execution?.error }}",
              "rightValue": "",
              "operator": {
                "type": "string",
                "operation": "isNotEmpty"
              }
            }
          ],
          "combinator": "and"
        }
      },
      "id": "error-trigger",
      "name": "Error Trigger",
      "type": "n8n-nodes-base.errorTrigger",
      "typeVersion": 1,
      "position": [240, 300]
    },
    {
      "parameters": {
        "jsCode": "// =============================================================\n// NODO CODE: FORMATEAR ERROR PARA TELEGRAM\n// =============================================================\n\nconst execution = $input.first().json.execution || {};\nconst workflow = $input.first().json.workflow || {};\n\n// Obtener información del error\nconst errorMessage = execution.error?.message || 'Error desconocido';\nconst errorNode = execution.error?.node?.name || 'Nodo desconocido';\nconst workflowName = workflow.name || 'Workflow desconocido';\nconst executionId = execution.id || 'N/A';\n\n// Intentar extraer el número de celular del contexto\nlet celular = 'No disponible';\ntry {\n  const data = execution.data?.resultData?.runData;\n  if (data && data['Set Fields']) {\n    celular = data['Set Fields'][0]?.data?.main?.[0]?.[0]?.json?.celular || 'No disponible';\n  }\n} catch (e) {\n  celular = 'Error extrayendo';\n}\n\nreturn [{\n  json: {\n    mensaje: `🚨 *ERROR EN WORKFLOW*\\n\\n*Workflow:* ${workflowName}\\n*Nodo que falló:* ${errorNode}\\n*Error:* ${errorMessage}\\n*Contacto:* ${celular}\\n*Execution ID:* ${executionId}\\n\\n_Revisar en n8n → Executions_`\n  }\n}];"
      },
      "id": "format-error",
      "name": "Formatear Error",
      "type": "n8n-nodes-base.code",
      "typeVersion": 2,
      "position": [460, 300]
    },
    {
      "parameters": {
        "chatId": "TU_CHAT_ID_TELEGRAM",
        "text": "={{ $json.mensaje }}",
        "additionalFields": {
          "parse_mode": "Markdown"
        }
      },
      "id": "telegram-error",
      "name": "Telegram Error",
      "type": "n8n-nodes-base.telegram",
      "typeVersion": 1.2,
      "position": [680, 300],
      "credentials": {
        "telegramApi": {
          "id": "TELEGRAM_CREDENTIAL_ID",
          "name": "Telegram Bot"
        }
      }
    }
  ],
  "connections": {
    "Error Trigger": {
      "main": [
        [
          {
            "node": "Formatear Error",
            "type": "main",
            "index": 0
          }
        ]
      ]
    },
    "Formatear Error": {
      "main": [
        [
          {
            "node": "Telegram Error",
            "type": "main",
            "index": 0
          }
        ]
      ]
    }
  },
  "active": true,
  "settings": {
    "executionOrder": "v1"
  }
}
```

### Configurar como Error Workflow:

1. Guardar el workflow "Error Handler"
2. Ir al workflow principal "Agente WhatsApp PoC"
3. Clic en "Settings" (engranaje en esquina superior derecha)
4. En "Error Workflow", seleccionar "Error Handler"
5. Guardar

---

## DIAGRAMA DE FLUJO ACTUALIZADO

```
Webhook Trigger
      ↓
Respond Immediately
      ↓
Set Fields
      ↓
Buscar en Notion (HTTP Request)
      ↓
Procesar Historial (Code) ← verifica rate limit + carga historial
      ↓
IF Rate Limit
   ├─ TRUE → Rate Limit Response (Code) → Wait → Evolution Send
   └─ FALSE ↓
            IF Filtro (original)
               ├─ FALSE → (termina)
               └─ TRUE ↓
                        AI Agent + Gemini + Memory
                              ↓
                        Code Delay
                              ↓
                        Wait
                              ↓
                        IF Escalar
                           ├─ TRUE → Telegram Handoff
                           └─ FALSE → Evolution API Send
                                           ↓
                                    Preparar Actualización (Code)
                                           ↓
                                    IF Contacto Existe
                                       ├─ TRUE → Actualizar Notion (PATCH)
                                       └─ FALSE → Crear Contacto Notion (POST)
                                           ↓
                                    IF Registrar Lead
                                       └─ TRUE → Crear Lead Notion (estado: interesado)
```

---

## RESUMEN DE PLACEHOLDERS A REEMPLAZAR

| Placeholder | Descripción | Dónde obtenerlo |
|-------------|-------------|-----------------|
| `TU_DATABASE_ID` | ID de 32 caracteres de tu base de datos Notion | URL de la base de datos |
| `TU_NOTION_TOKEN` | Token de integración (secret_xxx) | notion.so/my-integrations |
| `TU_CHAT_ID_TELEGRAM` | Tu Chat ID numérico | @userinfobot en Telegram |
