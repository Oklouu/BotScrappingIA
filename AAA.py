import os
import requests
import json
import discord
from discord import app_commands, Intents, AllowedMentions 
from discord.ext import tasks 
from bs4 import BeautifulSoup
from typing import Dict, Optional, Any
import asyncio 
import time      
import random    
import sqlite3

# =========================
# CONFIGURACIÓN ESENCIAL
# =========================

# ⚠️ Render: Leemos el token de la variable de entorno para seguridad.
TOKEN = os.getenv("DISCORD_BOT_TOKEN") 
# La ID de tu servidor (Guild)
GUILD_ID = 1434666150289211404 

# TASA DE RECARGO CALCULADA (5.5%)
RECARGO_RATE = 0.055 

# *** CONFIGURACIÓN DE NOTIFICACIONES ***
NOTIFICATION_CHANNEL_ID = 1435390692313792593 
# *************************

# --- CONFIGURACIÓN DE BASE DE DATOS ---
DB_NAME = "price_monitor.db" 

# --- DEFINICIÓN DE COMPONENTES BASE (SIN 'last_price') ---
BASE_COMPONENTS: Dict[str, Dict[str, str | int]] = {
    "CPU AMD Ryzen 5 5500": {
        "url": "https://www.myshop.cl/producto/cpu-amd-ryzen-5-5500-100-100000457box-p12965",
        "qty": 1
    },
    "Placa Madre Gigabyte A520M K V2": {
        "url": "https://www.myshop.cl/producto/mb-sam4-amd-gigabyte-a520m-k-v2-2x-ddr4-micro-atx-p32967",
        "qty": 1
    },
    "Fuente de Poder Redragon": {
        "url": "https://www.myshop.cl/producto/fuente-de-poder-redragon-gc-ps001-p28996",
        "qty": 1
    },
    "SSD M.2 NVMe 512GB": {
        "url": "https://www.myshop.cl/producto/wave-series-pcie-30-nvme-m2-ssd-512gb-p38735",
        "qty": 1
    },
    "RAM 8GB Kingston Fury Beast": {
        "url": "https://www.myshop.cl/producto/dimm-8-gb-kingston-fury-beast-3200mhz-ddr4-cl16-kf432c16bb8-p1671",
        "qty": 2 
    },
}

# --- LISTA GLOBAL DE MONITOREO ---
CART_ITEMS: Dict[str, Dict[str, str | int]] = {
    "Tarjeta de Video RX 7600": {
        "url": "https://www.myshop.cl/producto/tarjeta-de-video-asus-dual-rx7600-o8g-evo-8-gb-gddr6-128-bit-p35751",
        "qty": 1
    },
    "RTX 5050": { 
        "url": "https://www.myshop.cl/producto/tarjeta-de-video-zotac-geforce-rtx-5050-gaming-solo-8gb-gddr6-pci-e-50-displayport-hdmi-p38583",
        "qty": 1
    },
    **BASE_COMPONENTS
}

# --- CONFIGURACIÓN 1: BUILD RX 7600 ---
BUILD_RX7600: Dict[str, Dict[str, Any]] = {
    "Tarjeta de Video RX 7600": {
        "url": "https://www.myshop.cl/producto/tarjeta-de-video-asus-dual-rx7600-o8g-evo-8-gb-gddr6-128-bit-p35751",
        "qty": 1
    },
    **BASE_COMPONENTS
}

# --- CONFIGURACIÓN 2: BUILD RTX 5050 ---
BUILD_RTX5050: Dict[str, Dict[str, Any]] = {
    "RTX 5050": {
        "url": "https://www.myshop.cl/producto/tarjeta-de-video-zotac-geforce-rtx-5050-gaming-solo-8gb-gddr6-pci-e-50-displayport-hdmi-p38583",
        "qty": 1
    },
    **BASE_COMPONENTS
}


# =============================
#   FUNCIONES DE BASE DE DATOS 💾
# =============================
def init_db():
    """Inicializa la DB. Usa try/finally para asegurar que la conexión se cierre."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Crea la tabla.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                item_name TEXT PRIMARY KEY,
                last_price INTEGER,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()

        # Asegura que todos los componentes estén en la DB.
        for name in CART_ITEMS.keys():
            cursor.execute(
                "INSERT OR IGNORE INTO prices (item_name, last_price) VALUES (?, 0)", 
                (name,)
            )
        conn.commit()
        print(f"✅ DB inicializada o verificada: {DB_NAME}")
    except Exception as e:
        # Esto atrapará errores si el sistema de archivos de Render es demasiado restrictivo.
        print(f"❌ ERROR al inicializar la DB: {e}. El bot funcionará, pero perderá el historial.")
    finally:
        if conn:
            conn.close()

def get_last_price_from_db(item_name: str) -> int:
    """Obtiene el último precio de la DB, retornando 0 si falla la conexión."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT last_price FROM prices WHERE item_name = ?", (item_name,))
        result = cursor.fetchone()
        return result[0] if result else 0 
    except Exception:
        return 0
    finally:
        if conn:
            conn.close()

def update_price_in_db(item_name: str, new_price: int):
    """Actualiza el precio y el timestamp en la DB."""
    conn = None
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE prices SET last_price = ?, timestamp = CURRENT_TIMESTAMP WHERE item_name = ?", 
            (new_price, item_name)
        )
        conn.commit()
    except Exception:
        # Silenciamos el error si no podemos escribir en el disco no persistente.
        pass
    finally:
        if conn:
            conn.close()


# =============================
#   FUNCIÓN PARA EXTRAER PRECIO (SIN CAMBIOS)
# =============================
def fetch_price(url: str) -> Optional[int]:
    MAX_RETRIES = 3
    
    for attempt in range(MAX_RETRIES):
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            r = requests.get(url, headers=headers, timeout=5) 
            r.raise_for_status() 
            
            soup = BeautifulSoup(r.text, "html.parser")
            
            # Lógica de Parsing
            price_el_attr = soup.select_one('[data-price-amount]') 
            if price_el_attr:
                price_amount = price_el_attr.get('data-price-amount')
                if price_amount and price_amount.isdigit():
                    return int(price_amount)

            main_price_divs = soup.select('.main-price')
            for price_div in main_price_divs:
                text = None
                for sibling in price_div.next_siblings:
                    if isinstance(sibling, str) and sibling.strip().startswith('$'):
                        text = sibling.strip()
                        break
                if not text:
                     text = price_div.get_text(strip=True)

                if text:
                    clean_text = (
                        text.replace("$", "").replace(".", "").replace(",", "").replace("CLP", "").strip()
                    )
                    if clean_text.isdigit():
                        return int(clean_text)

            price_el = soup.select_one(".price, .precio, .product-price, .price-normal")
            if price_el:
                text = (
                    price_el.get_text(strip=True).replace("$", "").replace(".", "").replace(",", "").replace("CLP", "").strip()
                )
                if text.isdigit():
                    return int(text)

            return None
        
        except requests.exceptions.ConnectionError as e:
            if attempt < MAX_RETRIES - 1:
                print(f"⚠️ Reintento {attempt + 1}: Falló la conexión. Esperando 10 segundos...")
                time.sleep(10)
            else:
                print(f"❌ ERROR final en fetch_price para {url}: Falló la conexión después de {MAX_RETRIES} intentos.")
                return None
        
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                print(f"⚠️ Reintento {attempt + 1}: Error inesperado: {e}. Esperando 5 segundos...")
                time.sleep(5)
            else:
                print(f"❌ ERROR final en fetch_price para {url}: {e}")
                return None

    return None

# =============================
#   FUNCIÓN DE VERIFICACIÓN Y ACTUALIZACIÓN 
# =============================
def check_and_update_prices() -> list[str]:
    """
    Actualiza los precios usando fetch_price, compara con el precio en la DB 
    y retorna mensajes de cambio.
    """
    notification_messages = []
    
    for name, item in CART_ITEMS.items():
        url = item["url"]
        
        old_price = get_last_price_from_db(name)
        current_price = fetch_price(url)
        
        if current_price is not None and current_price > 0:
            
            if old_price == 0:
                change_status = "✅ **Cargado por primera vez**"
                notification_messages.append(f"• **{name}**: ${current_price:,}".replace(",", ".") + f" {change_status}")
            
            elif current_price != old_price:
                diff = current_price - old_price
                if diff > 0:
                    change_status = f"**⬆️ SUBIÓ** (+${diff:,})".replace(",", ".")
                else:
                    change_status = f"**⬇️ BAJÓ** (-${abs(diff):,})".replace(",", ".")
                notification_messages.append(f"• **{name}**: ${old_price:,} -> ${current_price:,}".replace(",", ".") + f" {change_status}")

            if current_price != old_price or old_price == 0:
                 update_price_in_db(name, current_price)
        
        # RETARDO ALEATORIO para evitar bloqueo de IP
        time.sleep(random.uniform(2, 5))
            
    return notification_messages


# =========================
# CONFIGURACIÓN DEL CLIENTE DISCORD
# =========================
class PriceClient(discord.Client):
    def __init__(self, *, intents: Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    # Tarea que se ejecuta cada 60 minutos (1 hora)
    @tasks.loop(minutes=60)
    async def price_check_task(self):
        await self.wait_until_ready() 
        notification_list = await self.loop.run_in_executor(None, check_and_update_prices)

        if notification_list and NOTIFICATION_CHANNEL_ID != 0:
            channel = self.get_channel(NOTIFICATION_CHANNEL_ID)
            if channel:
                header = "@everyone **🔔 CAMBIOS DE PRECIO DETECTADOS (MyShop)**" 
                message_content = "\n".join([header] + notification_list)
                allowed_mentions = AllowedMentions(everyone=True)

                if len(message_content) > 2000:
                    truncated_content = header + "\n" + "\n".join(notification_list[:5]) + "\n... (Más cambios)"
                    await channel.send(truncated_content, allowed_mentions=allowed_mentions)
                else:
                    await channel.send(message_content, allowed_mentions=allowed_mentions)

        print(f"✅ Tarea de 60 minutos completada. Cambios detectados: {len(notification_list)}")

    async def on_ready(self):
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
            
        print(f"BOT DISCORD INICIADO como {self.user} 🚀")
        
        if not self.price_check_task.is_running():
            self.price_check_task.start()

# Configurar Intents
intents = Intents.default()
intents.message_content = True 
client = PriceClient(intents=intents)

# =============================
#        COMANDO /carrito
# =============================
@client.tree.command(name="carrito", description="Muestra precios individuales y total de los artículos monitoreados.")
async def carrito_command(interaction: discord.Interaction):
    await interaction.response.send_message("🛒 Consultando y actualizando precios. Esto puede tomar un momento...", ephemeral=False)

    await client.loop.run_in_executor(None, check_and_update_prices) 

    message = ["**🛒 Precios Individuales del Carrito (Monitoreo):**"]
    total_neto = 0
    missing_items = []

    for name, item in CART_ITEMS.items():
        current_price = get_last_price_from_db(name) 
        qty = item["qty"]
        price_str = "❌ No disponible / Precio no cargado"
        
        if current_price > 0:
            price_total_item = current_price * qty
            total_neto += price_total_item
            price_unit_str = f"${current_price:,}".replace(",", ".")
            price_total_item_str = f"${price_total_item:,}".replace(",", ".")
            price_str = f"{price_unit_str} (x{qty} = {price_total_item_str})"
        else:
            missing_items.append(name)

        message.append(f"• **{name}**: {price_str}")

    if total_neto > 0:
        total_recargo = round(total_neto * RECARGO_RATE)
        total_final = total_neto + total_recargo

        message.append("\n**--- RESUMEN DEL TOTAL ---**")
        message.append(f"**Subtotal (Neto):** ${total_neto:,}".replace(",", "."))
        message.append(f"**Recargo ({RECARGO_RATE*100:.1f}%):** ${total_recargo:,}".replace(",", "."))
        message.append(f"**TOTAL FINAL:** ${int(round(total_final)):,}".replace(",", "."))

        if missing_items:
            message.append("\n⚠️ **Nota:** El total podría no ser preciso. No se encontró precio reciente para: " + ", ".join(missing_items))
    
    await interaction.edit_original_response(content="\n".join(message))


# =============================
#        COMANDO /total_build
# =============================
@client.tree.command(name="total_build", description="Calcula el precio total de una configuración específica de PC.")
@app_commands.describe(gpu="Elige la tarjeta gráfica para calcular la build.")
@app_commands.choices(gpu=[
    app_commands.Choice(name="Build RX 7600", value="RX7600"),
    app_commands.Choice(name="Build RTX 5050", value="RTX5050"),
])
async def total_build_command(interaction: discord.Interaction, gpu: app_commands.Choice[str]):
    await interaction.response.send_message(f"⏳ Calculando el total para la **{gpu.name}**. Esto tomará un momento...", ephemeral=False)
    
    if gpu.value == "RX7600":
        build_items = BUILD_RX7600
    elif gpu.value == "RTX5050":
        build_items = BUILD_RTX5050
    else:
        await interaction.edit_original_response(content="❌ Configuración no válida.")
        return

    def calculate_prices_on_demand():
        total_neto = 0
        missing_items = []
        message_details = [f"**🛒 Precios para la {gpu.name}:**"]
        
        for name, item in build_items.items():
            url = item["url"]
            qty = item["qty"]
            
            current_price = fetch_price(url) 
            price_str = "❌ No disponible"
            
            if current_price is not None and current_price > 0:
                price_total_item = current_price * qty
                total_neto += price_total_item
                price_unit_str = f"${current_price:,}".replace(",", ".")
                price_total_item_str = f"${price_total_item:,}".replace(",", ".")
                price_str = f"{price_unit_str} (x{qty} = {price_total_item_str})"
                
                # Actualizar la DB con el precio consultado bajo demanda
                update_price_in_db(name, current_price) 
            else:
                missing_items.append(name)

            message_details.append(f"• **{name}**: {price_str}")
            
            time.sleep(random.uniform(2, 5)) 

        return total_neto, missing_items, message_details

    total_neto, missing_items, message_details = await client.loop.run_in_executor(None, calculate_prices_on_demand)
    
    final_response = message_details
    
    if total_neto > 0:
        total_recargo = round(total_neto * RECARGO_RATE)
        total_final = total_neto + total_recargo

        final_response.append("\n**--- RESUMEN DEL TOTAL ---**")
        final_response.append(f"**Subtotal (Neto):** ${total_neto:,}".replace(",", "."))
        final_response.append(f"**Recargo ({RECARGO_RATE*100:.1f}%):** ${total_recargo:,}".replace(",", "."))
        final_response.append(f"**TOTAL FINAL:** ${int(round(total_final)):,}".replace(",", "."))

        if missing_items:
            final_response.append("\n⚠️ **Nota:** El total no incluye el precio de: " + ", ".join(missing_items))
    elif missing_items:
        final_response.append("\n❌ No se pudo calcular el total. Precios faltantes: " + ", ".join(missing_items))


    await interaction.edit_original_response(content="\n".join(final_response))


# === Inicializar y Ejecutar ===
if __name__ == "__main__":
    init_db() # Inicializar la DB antes de correr el bot.
    if TOKEN:
        try:
            client.run(TOKEN)
        except discord.errors.LoginFailure:
            print("❌ ERROR: El TOKEN de Discord es inválido. Verifica la variable DISCORD_BOT_TOKEN en Render.")
    else:
        print("❌ ERROR: La variable de entorno DISCORD_BOT_TOKEN no está configurada.")