# Handleiding: Meta AR/VR 3 (Quest 3) + Knitweb / MOLGANG

> **Let op:** Knitweb en MOLGANG hebben op dit moment (juni 2026) **geen eigen VR-app of WebXR-modus**. Deze handleiding gebruikt de **Meta Quest Browser** om de bestaande web-interfaces van Knitweb te bedienen in je headset. Alle acties (toevoegen, stemmen, verkennen, corrigeren) gebeuren via dezelfde P2P-webinterface die ook op desktop/telefoon werkt.

---

## 1. Wat je nodig hebt

| Benodigdheid | Toelichting |
|--------------|-------------|
| **Meta Quest 3** | Of een andere Quest-headset met de Meta Quest Browser. |
| **Internet** | Voor de publieke nodes op `5mart.ml`. |
| **Optioneel: eigen node** | Voor een privé-klaslokaal: `molgang serve` op een laptop/server in hetzelfde netwerk. |
| **Pen/vinger of controllers** | De webinterfaces zijn ontworpen voor muis/touch; in VR gebruik je de controller- of handcursor. |

---

## 2. Basisbegrippen (Knitweb-taal)

| Term | Betekenis in deze handleiding |
|------|-------------------------------|
| **Web** | Het gezamenlijke P2P-kennisweb. |
| **Knit** | Een twee-partij relatie/transfer (bijv. een chemische binding of een stem). |
| **Fiber** | Een onveranderlijke vastlegging van een accountstatus of geaccepteerd stukje kennis. |
| **Pulse / PLS** | De activiteitseenheid waarmee je stemt; gratis verkrijgbaar via de faucet. |
| **Silk** | Brandstof om een voorstel te doen. |
| **Spider** | Een P2P-werker die het web onderhoudt. |
| **MOLGANG** | Het leer-/speelweb gebouwd op Knitweb (chemie). |

> Volgens het project zelf noem je het een **web**, nooit een "netwerk" of "chain".

---

## 3. De Quest 3 openen en de browser starten

1. Zet je Quest 3 aan en zorg dat je verbonden bent met Wi-Fi.
2. Open de **Meta Quest Browser** (het blauwe bol-icoon).
3. Tik in de adresbalk en typ: `https://5mart.ml/molgang`
4. Druk op **Enter**.

Je ziet nu de **MOLGANG-bar**: een tafel waar je kunt zitten, termen kunt voorstellen en kunt stemmen.

> **3D-verkenner:** ga voor de 3D-weergave van het web naar `https://5mart.ml/knitweb`.

---

## 4. Aanmelden: wallet, silk en pulses ontvangen

Bij de eerste keer openen vraagt MOLGANG je om een naam en avatar.

1. Kies een **weergavenaam**.
2. Kies een **avatar**.
3. Tik op **Walk in / Join**.

Het spel maakt automatisch een **PLS-wallet** aan voor dit apparaat. Je krijgt gratis:
- **Silk** (om voorstellen te doen)
- **PLS pulses** (om te stemmen)

> Deze wallet blijft **stabiel** gekoppeld aan je apparaat. Als je later met dezelfde telefoon/Quest terugkomt, krijg je dezelfde account.

---

## 5. Toevoegen aan het Knitweb P2P (een term/bond voorstellen)

### 5.1 Neem plaats aan een tafel

1. Tik op een **vrije tafel** of kies **Sit at table**.
2. Je ziet de andere spelers (peers) aan je tafel, inclusief NPC-bots zodat er altijd een quorum mogelijk is.

### 5.2 Stel een chemische term of link voor

1. Tik in het invoerveld.
2. Type een term of link. Voorbeelden:
   - `H2O`
   - `H2O = water`
   - `H2 → O = H2O` (twee links)
3. Tik op **Knit** (kost 1 silk).

> Je voorstel wordt naar de tafel gestuurd. Andere spelers zien het nu in hun scherm.

### 5.3 Een spiral (meerdere links) voorstellen

Een **spiral** is een keten van 2 tot 7 links die je in één keer aan het web toevoegt:

1. Kies **Spiral**.
2. Voer elke link op een eigen regel in, bijvoorbeeld:
   ```
   H2 → O
   O2 → H2O
   ```
3. Tik op **Propose spiral**.

Hoe langer de spiral, hoe meer silk het kost. Hoe meer peers hem goedkeuren, hoe hoger je rank.

---

## 6. Stemmen (voting) in VR

Wanneer iemand anders een voorstel doet, verschijnt het bij jouw tafel.

1. Lees de voorgestelde term of link.
2. Beoordeel of deze chemisch correct is.
3. Tik op één van de knoppen:

| Stem | Betekenis |
|------|-----------|
| **✓ Confirm** | De term/link is correct. Je legt 1 PLS in als stem. |
| **✗ Mismatch** | De term/link is fout. Je legt 1 PLS in als tegenstem. |
| **– Abstain** | Je weet het niet zeker. |

### Hoe wordt een voorstel geaccepteerd?

- Zodra **alle zittende spelers gestemd** hebben, telt het spel de stemmen.
- Er is een **Byzantine-fault-tolerant quorum** nodig (meerderheid van ⅔ + 1).
- Bij acceptatie:
  - De term wordt **gewoven** in het gedeelde web als een Fiber.
  - De voorsteller krijgt zijn silk terug en verdient pulses.
  - Bevestigende stemmers krijgen hun inzet terug plus een beloning.
- Bij afwijzing:
  - De term komt **niet** in het web.
  - De inzetten worden terugbetaald.

---

## 7. Het Knitweb verkennen in VR

### 7.1 De 3D-weergave openen

1. Open in de Quest Browser: `https://5mart.ml/knitweb`
2. Je ziet een 3D-netwerk van nodes (begrippen) en links (relaties).
3. Standaard laadt de **Live chem-web** (ongeveer 448 nodes, 948 edges).

### 7.2 Bediening in VR

| Actie | Hoe in Quest 3 |
|-------|----------------|
| **Draaien / roteren** | Sleep met de controller door de lege achtergrond. |
| **Inzoomen** | Scroll met de controller-thumbstick of pinch-beweging. |
| **Node verplaatsen** | Pak een bolletje vast en sleep het. |
| **Node centreren** | Tik op een node; de camera vliegt ernaartoe. |
| **Details zien** | Houd de cursor boven een node of link; info verschijnt in het rechterpaneel. |
| **Taal wisselen** | Kies **EN / RU / 中文 / AR** in het menu. |
| **Zoeken** | Typ een term (bijv. `H2O`) in het zoekveld. |

### 7.3 Wat je ziet

- **Nodes** = chemische begrippen (elementen, moleculen).
- **Links** = relaties zoals `part-of`, `is-a`, `reacts-with`.
- **Kleuren** = status van een link:
  - **Cyaan** = strak / goed bevestigd
  - **Roze** = neutraal
  - **Grijs** = slap / weinig steun
  - **Oranje** = betwist of "gesnapt"

### 7.4 De lokale 2D-explorer (optioneel)

Als je een eigen `molgang` node draait:

```bash
molgang explore
```

Open dan op je Quest: `http://<ip-van-je-pc>:8990`

Deze geeft:
- Statistieken (`/api/kg/stats`)
- Centrale knooppunten (`/api/kg/hubs`)
- Kortste pad tussen twee termen (`/api/kg/path`)
- Buren van een concept (`/api/kg/neighbors`)

---

## 8. Fouten corrigeren

In Knitweb/MOLGANG corrigeer je fouten **door te stemmen**, niet door te wissen.

### 8.1 Voorkomen: stemmen tijdens de ronde

- Stem **✗ Mismatch** op elk verkeerd voorstel.
- Als genoeg peers het eens zijn, wordt het voorstel **afgewezen** en komt het nooit in het web.

### 8.2 Al geweven: concurrerende knits en tension

Als een fout toch in het web is gekomen:

1. **Open de Explorer** (`5mart.ml/knitweb`).
2. Zoek de betwiste term.
3. Kijk naar de **tension-kleur** (oranje = betwist).
4. Doe een **tegenvoorstel**:
   - Stel de correcte term/link voor in MOLGANG.
   - Laat peers bevestigen.
5. De explorer rangschikt knits op basis van `confirm − mismatch`. De beter onderbouwde versie wint aan zichtbaarheid.
6. Links met te weinig steun (`T < 300`) worden uiteindelijk door `prune_slack` uit de actieve graaf verwijderd.

> Er is **geen bewerk-knop** voor een Fiber; dit is bewust ontworpen zodat alle kennis traceerbaar blijft via het stemverleden.

---

## 9. PoUW-certificaat opvragen (optioneel)

Als bewijs van je werk kun je een **Proof-of-Useful-Work-certificaat** downloaden:

1. Tik in de MOLGANG-bar op **🏅 Request PoUW Certificate**.
2. Het certificaat wordt als PDF gedownload.
3. Deze bevat:
   - Je wallet-adres en publieke sleutel
   - Hoeveel pulses je hebt gebruikt
   - Hoeveel knits/spirals je hebt geweven
   - Hoeveel stemmen je hebt uitgebracht
   - De OriginTrail UAL (provenance)

> Via de browser/API wordt altijd de **publieke modus** gebruikt. Privé-sleutels worden nooit gedeeld.

---

## 10. Zelf een lokale node draaien (voor docenten/klassen)

Wil je een privé-omgeving in de klas?

```bash
# Op een laptop/server
git clone https://github.com/knitweb/molgang.git
cd molgang
./install.sh
source .venv/bin/activate
molgang serve --host 0.0.0.0 --port 8765
```

Op de Quest 3:
1. Open de Meta Quest Browser.
2. Ga naar `http://<ip-van-de-laptop>:8765`.
3. Alle leerlingen kunnen nu dezelfde bar gebruiken.

Voor de 3D-explorer:

```bash
molgang explore --host 0.0.0.0 --port 8990
```

Open op de Quest: `http://<ip-van-de-laptop>:8990`

---

## 11. Samenvatting van URLs

| Doel | URL |
|------|-----|
| MOLGANG spelen (stemmen, toevoegen) | `https://5mart.ml/molgang` |
| 3D-web verkennen | `https://5mart.ml/knitweb` |
| Lokale bar | `http://<ip>:8765` |
| Lokale explorer | `http://<ip>:8990` |
| Broncode | `https://github.com/knitweb/pulse` en `https://github.com/knitweb/molgang` |

---

## 12. Tips voor VR-gebruik

- **Zet de Quest in staand of zittend gebruik** zodat je comfortabel naar het virtuele browserscherm kijkt.
- **Gebruik de controller-cursor**; tikken op kleine knoppen gaat het fijnst met de controllerstraal.
- **Verhoog de schermgrootte** van het browservenster in de Quest Browser voor betere leesbaarheid.
- **Sla belangrijke URLs op als bladwijzer** in de Quest Browser.
- **Let op batterij en warmte**: de 3D-weergave vraagt veel van de Quest.

---

*Handleiding gegenereerd op basis van de publieke Knitweb/MOLGANG-documentatie en de live sites op 5mart.ml (juni 2026).*
