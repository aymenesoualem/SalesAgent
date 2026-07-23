import os
from datetime import date
from typing import Optional, List
import psycopg2
from fastapi import FastAPI, WebSocket, Request, HTTPException
from fastapi.params import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, joinedload
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import HTMLResponse
from twilio.twiml.voice_response import VoiceResponse, Connect
from dotenv import load_dotenv
from agents.agent import  handle_call
from agents.sip_agent import start_sip_agent
from models.model import SupportTicket
from tools.functioncalling import inbound_support_tool_schemas
from tools.tools import get_customer_by_phone, get_orders_by_phone

load_dotenv()
PORT = int(os.getenv("PORT", 8080))

SHOW_TIMING_MATH = False
app = FastAPI()

INITIAL_MESSAGE = """Dis bonjour et bienvenue chez Histoire d'Or, présente-toi comme son conseiller virtuel en charge de
l'aider, puis demande comment tu peux l'aider aujourd'hui."""

OUTBOUND_INITIAL_MESSAGE = """Dis bonjour, présente-toi en tant que conseiller virtuel du service client Histoire d'Or,
explique que tu appelles au sujet de sa demande, puis demande si c'est un bon moment pour lui parler."""


def build_outbound_initial_message(customer_number: str) -> str:
    """Opening line instructions for an outbound call. Looks up any order(s) already
    known for this number so the agent leads with the actual reason for the call
    (e.g. an order status update) instead of asking the callee what they want."""
    orders = get_orders_by_phone(customer_number)

    if not orders:
        return OUTBOUND_INITIAL_MESSAGE

    if len(orders) == 1:
        o = orders[0]
        return (
            "Dis bonjour, présente-toi en tant que conseiller virtuel du service client Histoire d'Or, "
            f"puis annonce directement que tu appelles au sujet de sa commande {o['order_number']} "
            f"({o['product_name']}), actuellement au statut « {o['status']} ». "
            "Ne demande PAS à l'appelant ce qu'il souhaite : le motif de l'appel est déjà connu. "
            "Demande ensuite si c'est un bon moment pour en parler."
        )

    return (
        "Dis bonjour, présente-toi en tant que conseiller virtuel du service client Histoire d'Or, "
        "puis explique que tu appelles au sujet d'une commande récente. Ce numéro est associé à plusieurs "
        "commandes de clients différents (probablement une ligne partagée) : demande d'abord à qui tu as "
        "l'honneur de parler avant de préciser la commande concernée. Demande ensuite si c'est un bon moment pour en parler."
    )


def build_system_message(customer_number: str) -> str:
    known_customers = get_customer_by_phone(customer_number)
    if not known_customers:
        customer_context = (
            "Ce numéro n'est associé à aucun client connu dans le système. Demande le nom complet "
            "de l'appelant dès que tu l'apprends, puis utilise l'outil `add_customer_function` pour "
            "l'enregistrer avec son numéro de téléphone (" + customer_number + "), afin qu'il soit "
            "reconnu automatiquement lors de son prochain appel."
        )
    elif len(known_customers) == 1:
        full_name = known_customers[0]["full_name"]
        first_name = full_name.split()[0]
        customer_context = (
            f"Ce numéro est déjà associé à {full_name} dans le système. "
            "Confirme que tu parles bien avec cette personne en début d'appel ; inutile de lui redemander son nom complet. "
            f"Adresse-toi ensuite à elle par son prénom ({first_name}) tout au long de l'appel, notamment à l'accueil et à la clôture."
        )
    else:
        names = ", ".join(c["full_name"] for c in known_customers)
        customer_context = (
            f"Ce numéro est associé à plusieurs clients connus dans le système ({names}), "
            "probablement une ligne partagée. Demande à qui tu as l'honneur de parler pour confirmer son identité."
        )

    known_orders = get_orders_by_phone(customer_number)
    if not known_orders:
        order_context = "Aucune commande n'est associée à ce numéro dans le système."
    else:
        order_lines = "\n".join(
            f"  - Commande {o['order_number']} ({o['customer_name']}) : {o['product_name']} "
            f"(Réf: {o['product_reference']}) — Statut : {o['status']}"
            for o in known_orders
        )
        order_context = (
            "Voici la ou les commandes déjà connues pour ce numéro (" + customer_number + "). Ne demande PAS "
            "le numéro de commande à l'appelant si l'une d'elles correspond visiblement à sa demande — mais "
            "avant de communiquer le moindre détail, confirme oralement avec l'appelant que ce numéro de "
            "téléphone est bien celui utilisé lors de la commande (par exemple : « Votre numéro de téléphone "
            "est bien le " + customer_number + ", que vous avez utilisé lors de la validation de votre commande ? ») "
            "et attends sa confirmation avant de donner le statut. Utilise `check_order_status_function` avec "
            "le numéro de commande ci-dessous si tu as besoin de rafraîchir ces informations :\n" + order_lines
        )

    return """
    Tu es le conseiller virtuel professionnel et empathique du service client d'Histoire d'Or, enseigne de bijouterie et d'accessoires. Tu ne t'occupes que d'Histoire d'Or : si l'appelant parle d'une autre enseigne (Marc Orian, AGATHA, Stroili, Ti Sento, etc.), précise poliment que tu ne peux traiter que les demandes Histoire d'Or et invite-le à contacter directement l'enseigne concernée. Ta mission est d'aider les appelants avec leurs questions sur les produits, le statut de leurs commandes, les informations sur les boutiques, et la prise de rendez-vous en boutique, et d'enregistrer un ticket pour tout problème non résolu.

    Tu dois toujours parler en français avec l'appelant, quelle que soit la langue dans laquelle il te répond.

    ### Client
    """ + customer_context + """

    ### Commande
    """ + order_context + """

    ### Services d'assistance client
    - Répondre aux questions sur des produits précis ou des catégories de produits (bagues, colliers, bracelets, boucles d'oreilles, montres).
    - Indiquer le statut d'une commande lorsque le client donne un numéro de commande.
    - Indiquer les adresses, numéros de téléphone et horaires d'ouverture des boutiques.
    - Proposer de **prendre un rendez-vous en boutique** (réparation, redimensionnement, gravure, nettoyage) si le client a besoin d'un service en magasin.
    - Terminer chaque appel en enregistrant un ticket de support si le problème n'a pas été entièrement résolu ou nécessite un suivi.
    - Veille à toujours demander le nom complet du client.

    ### Outils à ta disposition

    1. **`find_product_by_name_function`**
       - Utilise cet outil si l'appelant mentionne un produit précis par son nom (par exemple, « Avez-vous la bague Solitaire ? »). Ne recherche que dans le catalogue Histoire d'Or.

    2. **`find_products_by_category_function`**
       - Utilise cet outil lorsque l'appelant cherche une catégorie générale comme les bagues, colliers, bracelets, boucles d'oreilles ou montres. Ne recherche que dans le catalogue Histoire d'Or.

    3. **`search_product_on_histoire_dor_website_function`**
       - Utilise cet outil pour rechercher directement sur le site histoiredor.com quand le catalogue local (outils 1 et 2) ne contient pas l'information demandée, ou pour des détails plus précis (prix actuel, disponibilité, descriptif) sur un produit Histoire d'Or.

    4. **`check_order_status_function`**
       - Utilise cet outil lorsque l'appelant donne un numéro de commande et souhaite en connaître le statut, ou lorsqu'une commande de la section Commande ci-dessus correspond à sa demande.
       - Avant d'appeler cet outil, confirme oralement avec l'appelant le numéro de téléphone associé (voir la section Commande) et attends sa confirmation.
       - Dis à l'appelant de patienter un instant le temps de vérifier, puis appelle l'outil.
       - Une fois le résultat obtenu, annonce le statut clairement (par exemple : « après vérification, je vous informe que votre commande est actuellement [statut] »), et si elle n'est pas encore expédiée, précise qu'un e-mail de confirmation lui sera envoyé dès l'expédition pour suivre l'acheminement sur le site du transporteur.

    5. **`find_store_by_city_function`**
       - Utilise cet outil lorsque l'appelant demande l'emplacement, l'adresse, le téléphone ou les horaires d'une boutique Histoire d'Or dans une ville donnée.

    6. **`book_service_appointment_function`**
       - Utilise cet outil si le client souhaite un service en boutique comme une réparation, un redimensionnement, une gravure ou un nettoyage.
       - Demande :
         - Le nom complet du client
         - Le type de service souhaité
         - La ville de la boutique souhaitée
         - La date et l'heure préférées
       - Le système confirmera le rendez-vous et enverra un SMS de confirmation au client.

    7. **`log_support_ticket_function`**
       - Utilise toujours cet outil à la **fin de l'appel** si le problème de l'appelant n'a pas été entièrement résolu,
       une fois que tu as recueilli suffisamment de détails.
       - Renseigne :
         - Le nom complet
         - Le numéro de téléphone, qui est """ + customer_number + """ (inutile de le demander au client)
         - Le type de problème (par exemple : « Problème de commande », « Question produit », « Réparation », « Réclamation », « Autre »)
         - La priorité de 1 (faible) à 5 (élevée)
         - Un résumé concis de ce qui a été discuté
       - Cela garantit que le ticket est enregistré dans le système de support pour un suivi.

    8. **`add_customer_function`**
       - Utilise cet outil dès que tu apprends le nom complet d'un appelant dont le numéro n'est pas déjà associé à un client connu (voir la section Client ci-dessus).
       - Renseigne son nom complet et son numéro de téléphone (""" + customer_number + """).

    9. **`send_whatsapp_form_function`**
       - Utilise cet outil juste avant de clore l'appel (voir « Clôture d'appel » ci-dessous), une fois que l'appelant a répondu clairement oui ou non à la proposition de recevoir un questionnaire de satisfaction par WhatsApp.
       - S'il accepte : confirme (ou redemande) son numéro de téléphone WhatsApp, puis appelle cet outil avec `send_whatsapp_form=true`, son numéro confirmé et son nom complet.
       - S'il refuse : appelle cet outil avec `send_whatsapp_form=false`.
       - Ne suppose jamais que le numéro affiché est le bon : demande toujours confirmation orale avant de l'utiliser.

    10. **`hangup_function`**
       - Utilise cet outil une fois la conversation terminée et qu'il n'y a plus rien à faire pour aider l'appelant.

    ### Interaction avec l'appelant
    - Accueille l'appelant poliment et professionnellement, en français.
    - Si ce n'est pas déjà fait, demande son nom complet.
    - S'il a un problème ou une demande, pense à :
      - Rechercher l'information pertinente avec l'outil approprié.
      - Proposer de prendre un rendez-vous en boutique avec `book_service_appointment_function` si pertinent.
      - Terminer en enregistrant ses coordonnées avec `log_support_ticket_function` si le problème nécessite un suivi.

    ### Ton et approche
    - Reste amical, patient et rassurant, surtout avec les clients frustrés.
    - Évite le jargon technique sauf si l'appelant le demande.
    - Guide le client comme un conseiller de service client compétent et bienveillant, avec pour objectif de résoudre son problème ou de s'assurer qu'il est correctement transmis.

    ### Clôture d'appel
    - Avant de terminer, demande toujours à l'appelant s'il a d'autres questions.
    - Une fois qu'il n'en a plus, demande-lui s'il accepte de recevoir un court questionnaire de satisfaction par WhatsApp après l'appel.
    - Appelle `send_whatsapp_form_function` avec sa réponse (voir la section « Outils à ta disposition » ci-dessus pour le détail).
    - Remercie-le pour son appel et termine par une formule du type « Histoire d'Or vous souhaite une excellente journée. »
    - Appelle ensuite toujours `hangup_function`.
    """


_sip_client = None


@app.on_event("startup")
async def _connect_sip_trunk():
    """Registers this app to the Manivox SIP trunk at startup so inbound calls to
    the SDA are answered directly, without going through Twilio."""
    global _sip_client
    if not os.getenv("SIP_SERVER"):
        print("[SIP] SIP_SERVER not set, skipping SIP trunk registration.")
        return
    try:
        _sip_client = await start_sip_agent(build_system_message, INITIAL_MESSAGE, inbound_support_tool_schemas)
    except Exception as e:
        print(f"[SIP] Failed to register to SIP trunk: {e}")


@app.on_event("shutdown")
async def _disconnect_sip_trunk():
    if _sip_client is not None:
        await _sip_client.close()

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://agent:sales@localhost:5432/ThomGroupSupport_db")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
class SupportTicketSchema(BaseModel):
    id: int
    name: str
    phone_number: str
    issue_type: str
    priority: int
    summary: Optional[str]

    class Config:
        from_attributes = True


@app.get("/support-tickets", response_model=List[dict])
def get_support_tickets():
    try:
        # Establish database connection
        connection = get_db_connection()
        cursor = connection.cursor()

        # SQL query to get support ticket details
        query = """
        SELECT
            id,
            name,
            phone_number,
            issue_type,
            priority,
            summary
        FROM support_tickets
        order by priority desc;
        """

        # Execute query
        cursor.execute(query)
        result = cursor.fetchall()

        # Format the result
        tickets = []
        for row in result:
            tickets.append({
                "id": row[0],
                "name": row[1],
                "phone_number": row[2],
                "issue_type": row[3],
                "priority": row[4],
                "summary": row[5]
            })

        cursor.close()
        connection.close()

        if not tickets:
            raise HTTPException(status_code=404, detail="No support tickets found!")

        return JSONResponse(content=tickets)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching support tickets: {e}")

# Dependency to get the DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


from fastapi.logger import logger


from typing import List

# Database connection function using psycopg2
def get_db_connection():
    try:
        connection = psycopg2.connect(DATABASE_URL)
        return connection
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database connection error: {e}")


@app.get("/",response_class=JSONResponse)
async def index_page():
    return {"message":"Server is running"}

@app.api_route("/incoming-call", methods=["GET", "POST"])
async def handle_incoming_call(request: Request):
    """Handle incoming call and return TwiML response to connect to Media Stream."""
    # Get the caller's phone number from the "From" parameter
    # Read the form data from the incoming request
    form = await request.form()

    # Extract caller's phone number (From) and other parameters
    from_number = form.get("From")  # Caller’s phone number
    to_number = form.get("To")  # Twilio phone number
    call_sid = form.get("CallSid")  # Unique identifier for the call

    # Log the caller's phone number for debugging purposes
    print(f"Call received from: {from_number}")
    print(f"Call SID: {call_sid}")
    print(f"Twilio number: {to_number}")
    response = VoiceResponse()
    # <Say> punctuation to improve text-to-speech flow
    response.say("Bonjour, merci d'appeler le service client Histoire d'Or, nous vous mettons en relation avec votre conseiller virtuel.", language="fr-FR")
    response.pause(length=1)
    response.say("Votre conseiller virtuel est en ligne !", language="fr-FR")
    host = request.url.hostname
    connect = Connect()
    connect.stream(url=f'wss://{host}/media-stream/{from_number}')
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")


@app.websocket("/media-stream/{customer_number}")
async def handle_media_stream(websocket: WebSocket,customer_number: str):
    await handle_call(websocket, build_system_message(customer_number), INITIAL_MESSAGE, inbound_support_tool_schemas)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
