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

# =========================
# CONFIGURACIÓN ESENCIAL
# =========================
# ¡REEMPLAZA ESTO!
TOKEN = "---" 
# La ID de tu servidor (Guild)
GUILD_ID = 

# TASA DE RECARGO CALCULADA (5.5%)
RECARGO_RATE = 0.055 

# *** CONFIGURACIÓN DE NOTIFICACIONES ***
NOTIFICATION_CHANNEL_ID =  
# *************************

# --- DEFINICIÓN DE COMPONENTES BASE (Para simplificar la creación de builds) ---
BASE_COMPONENTS: Dict[str, Dict[str, str | int]] = {
    "CPU AMD Ryzen 5 5500": {
        "url": "https://www.myshop.cl/producto/cpu-amd-ryzen-5-5500-100-100000457box-p12965",
        "last_price": 0,
        "qty": 1
    },
    "Placa Madre Gigabyte A520M K V2": {
        "url": "https://www.myshop.cl/producto/mb-sam4-amd-gigabyte-a520m-k-v2-2x-ddr4-micro-atx-p32967",
        "last_price": 0,
        "qty": 1
    },
    "Fuente de Poder Redragon": {
        "url": "https://www.myshop.cl/producto/fuente-de-poder-redragon-gc-ps001-p28996",
        "last_price": 0,
        "qty": 1
    },
    "SSD M.2 NVMe 512GB": {
        "url": "https://www.myshop.cl/producto/wave-series-pcie-30-nvme-m2-ssd-512gb-p38735",
        "last_price": 0,
        "qty": 1
    },
    "RAM 8GB Kingston Fury Beast": {
        "url": "https://www.myshop.cl/producto/dimm-8-gb-kingston-fury-beast-3200mhz-ddr4-cl16-kf432c16bb8-p1671",
        "last_price": 0,
        "qty": 2 
    },
}

# --- LISTA GLOBAL DE MONITOREO (Solo RX 7600 y componentes base) ---
CART_ITEMS: Dict[str, Dict[str, str | int]] = {
    "Tarjeta de Video RX 7600": {
        "url": "https://www.myshop.cl/producto/tarjeta-de-video-asus-dual-rx7600-o8g-evo-8-gb-gddr6-128-bit-p35751",
        "last_price": 0,
        "qty": 1
    },
        "RTX 5050": {  # ← ¡AGREGA ESTO!
        "url": "https://www.myshop.cl/producto/tarjeta-de-video-zotac-geforce-rtx-5050-gaming-solo-8gb-gddr6-pci-e-50-displayport-hdmi-p38583",
        "last_price": 0,
        "qty": 1
    },
    **BASE_COMPONENTS
}

# --- CONFIGURACIÓN 1: BUILD RX 7600 (Para el comando /total_build) ---
BUILD_RX7600: Dict[str, Dict[str, Any]] = {
    "Tarjeta de Video RX 7600": {
        "url": "https://www.myshop.cl/producto/tarjeta-de-video-asus-dual-rx7600-o8g-evo-8-gb-gddr6-128-bit-p35751",
        "qty": 1
    },
    **BASE_COMPONENTS
}

# --- CONFIGURACIÓN 2: BUILD RTX 5050 (Para el comando /total_build) ---
BUILD_RTX5050: Dict[str, Dict[str, Any]] = {
    "RTX 5050": {
        "url": "https://www.myshop.cl/producto/tarjeta-de-video-zotac-geforce-rtx-5050-gaming-solo-8gb-gddr6-pci-e-50-displayport-hdmi-p38583",
        "qty": 1
    },
    **BASE_COMPONENTS
}


# =============================
#   FUNCIÓN PARA EXTRAER PRECIO (CON LÓGICA DE REINTENTO)
# =============================
def fetch_price(url: str) -> Optional[int]:
    MAX_RETRIES = 3
    
    for attempt in range(MAX_RETRIES):
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            r = requests.get(url, headers=headers, timeout=5) 
            r.raise_for_status() 
            
            soup = BeautifulSoup(r.text, "html.parser")
            
            # Lógica de Parsing (Simplificada para el ejemplo)
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
                print(f"⚠️ Reintento {attempt + 1}: Falló la conexión (ERROR 10054). Esperando 10 segundos...")
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
#   FUNCIÓN DE VERIFICACIÓN Y ACTUALIZACIÓN (Para la Tarea de 60 mins)
# =============================
def check_and_update_prices() -> list[str]:
    """
    Actualiza los precios de CART_ITEMS y retorna mensajes de cambio con retardos.
    """
    global CART_ITEMS
    notification_messages = []
    
    for name, item in CART_ITEMS.items():
        url = item["url"]
        old_price = item["last_price"]
        
        current_price = fetch_price(url)
        
        if current_price is not None:
            
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

            CART_ITEMS[name]["last_price"] = current_price
        
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
                    await channel.send(header + "\n" + "\n".join(notification_list[:5]) + "\n...", allowed_mentions=allowed_mentions)
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
#        COMANDO /carrito (Muestra individuales y el total de la BUILD DE MONITOREO)
# =============================
@client.tree.command(name="carrito", description="Muestra precios individuales y total de los artículos monitoreados.")
async def carrito_command(interaction: discord.Interaction):
    global CART_ITEMS
    await interaction.response.send_message("🛒 Consultando y actualizando precios. Esto puede tomar un momento...", ephemeral=False)

    await client.loop.run_in_executor(None, check_and_update_prices) 

    message = ["**🛒 Precios Individuales del Carrito (Monitoreo):**"]
    total_neto = 0
    missing_items = []

    for name, item in CART_ITEMS.items():
        current_price = item["last_price"] 
        qty = item["qty"]
        price_str = "❌ No disponible"
        
        if current_price is not None and current_price > 0:
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
            message.append("\n⚠️ **Nota:** El total no incluye el precio de: " + ", ".join(missing_items))
    
    await interaction.edit_original_response(content="\n".join(message))


# =============================
#        NUEVO COMANDO /total_build (Para elegir configuración)
# =============================
@client.tree.command(name="total_build", description="Calcula el precio total de una configuración específica de PC.")
@app_commands.describe(gpu="Elige la tarjeta gráfica para calcular la build.")
@app_commands.choices(gpu=[
    app_commands.Choice(name="Build RX 7600", value="RX7600"),
    app_commands.Choice(name="Build RTX 5050", value="RTX5050"),
])
async def total_build_command(interaction: discord.Interaction, gpu: app_commands.Choice[str]):
    await interaction.response.send_message(f"⏳ Calculando el total para la **{gpu.name}**. Esto tomará un momento...", ephemeral=False)
    
    # 1. Seleccionar la configuración
    if gpu.value == "RX7600":
        build_items = BUILD_RX7600
    elif gpu.value == "RTX5050":
        build_items = BUILD_RTX5050
    else:
        await interaction.edit_original_response(content="❌ Configuración no válida.")
        return

    # 2. Calcular el total (Fetch prices on demand)
    total_neto = 0
    missing_items = []
    message_details = [f"**🛒 Precios para la {gpu.name}:**"]

    # Usamos un bucle síncrono en el executor para no bloquear el bot
    def calculate_prices():
        nonlocal total_neto
        nonlocal missing_items
        nonlocal message_details
        
        for name, item in build_items.items():
            url = item["url"]
            qty = item["qty"]
            
            # Fetch price con reintentos y lógica de bloqueo
            current_price = fetch_price(url) 
            
            price_str = "❌ No disponible"
            
            if current_price is not None and current_price > 0:
                price_total_item = current_price * qty
                total_neto += price_total_item
                price_unit_str = f"${current_price:,}".replace(",", ".")
                price_total_item_str = f"${price_total_item:,}".replace(",", ".")
                price_str = f"{price_unit_str} (x{qty} = {price_total_item_str})"
            else:
                missing_items.append(name)

            message_details.append(f"• **{name}**: {price_str}")
            
            # Retardo aleatorio entre peticiones para evitar bloqueo
            time.sleep(random.uniform(2, 5)) 

    # Ejecutar el cálculo en el executor
    await client.loop.run_in_executor(None, calculate_prices)

    # 3. Generar la respuesta final
    
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


# Ejecutar el bot
client.run(TOKEN)
