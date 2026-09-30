# ELOS v19 — Contexto Completo do Projeto
> Documento gerado para nutrir uma nova sessão Claude Code com todo o contexto desta conversa.  
> Última atualização: 2026-09-29

---

## 1. Identidade do Projeto

**ELOS** é uma ferramenta de mapeamento relacional clínico 3D — genograma + ecomapa + teoria Bowen + linha do tempo — desenvolvida como **aplicação web single-file** (um único `elos_v19.html`).

- **Autora/proprietária:** Rodrigo Josiman Serafim Barros  
- **Email:** rodrigobarros81@gmail.com  
- **Contexto acadêmico:** Mestrado em Saúde Coletiva  
- **Deploy:** Netlify (conta: med.rjsb@gmail.com) via drag-and-drop do HTML  
- **Backend:** Supabase (projeto `wnsufourebpvgikkvuig`)  
- **Versão atual:** v19 (a mais recente — todas as mudanças desta conversa estão nela)

---

## 2. Arquivo Principal

```
elos_v19.html          ← O ÚNICO arquivo de entrega (~190 KB)
```

Todo CSS, JavaScript, HTML e dados estão **inline neste único arquivo**. Não há pasta `src/`, não há `package.json`, não há build step. O arquivo é servido diretamente pelo Netlify.

**Localização na sessão anterior:**  
`/tmp/claude-0/-home-claude/dec77047-e372-5436-87e3-c5c1a2ae1c75/scratchpad/elos_v19.html`

---

## 3. Stack Técnica

| Camada | Tecnologia |
|---|---|
| Renderização 3D | Three.js r128 (carregado via CDN cdnjs) |
| Controles de câmera | `OrbitControls` (Three.js addon) |
| UI / Overlay | HTML + CSS puro (modais, menus, topbar) |
| Backend | Supabase REST API (anon key) |
| Deploy | Netlify (single-file drop) |
| Framework JS | Nenhum — vanilla JS |

**CDN Three.js (verbatim — não alterar versão sem testar):**
```html
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
```

---

## 4. Variáveis e Arrays Globais Críticos

```javascript
// Arrays de estado principal
let PEOPLE  = [];   // [{id, name, gender, birth, rel, gen, focus, deceased, x, y, z, ...}]
let BONDS   = [];   // [{a, b, type, label}]
let ECO_NODES = []; // [{id, name, category, x, y, z, ...}]
let ECO_BONDS = []; // [{a, b, ...}]

// Registros de malhas 3D
let nodeMap    = {};   // {id: {mesh, label, data}} — PESSOAS e ECO
let extNodeMap = {};   // nós de extensão de genograma

// Arrays de camadas (para applyLayers())
let genLayer   = [];   // objetos do genograma (casamentos, filhos, etc.)
let bowenLayer = [];   // objetos de vínculos Bowen/relacionais
let ecoLayer   = [];   // objetos do ecomapa
let ecoMeshes  = [];   // meshes de nós eco (redundante mas necessário para applyLayers)

// Three.js
let scene, camera, renderer, controls, clock, aniId;
let labelRenderer; // CSS2DRenderer para labels flutuantes

// Estado de interação
let ctxPersonId = null;  // ID da pessoa clicada com botão direito
let selectedId  = null;  // ID da pessoa selecionada no clique simples
```

---

## 5. Sistemas de Posicionamento

### 5.1 `voiceBuild()` — construção via array de dados

Usa o mapa `FIXED_POS` com coordenadas canônicas por **papel familiar**:

```javascript
const FIXED_POS = {
  'Bisavô':      {x:-32, y:38, z:0},
  'Bisavó':      {x:-18, y:38, z:0},
  'Avô Paterno': {x:-20, y:22, z:0},
  'Avó Paterna': {x:-8,  y:22, z:0},
  'Avô Materno': {x:8,   y:22, z:0},
  'Avó Materna': {x:20,  y:22, z:0},
  'Pai':         {x:-8,  y:6,  z:0},
  'Mãe':         {x:8,   y:6,  z:0},
  'Pessoa Foco': {x:0,   y:-10, z:0},
  'Cônjuge':     {x:18,  y:-10, z:0},
  // Filhos: x centrado, y:-24, espaçamento 12
  // Netos:  y:-36
  // Irmãos: x:-12 * índice (lado esquerdo), y geração Pai
  // Tios/Primos: plano z:10
};
```

### 5.2 `confirmAdd()` — formulário "+ Pessoa"

Espelha `FIXED_POS` com lógica adicional por índice de siblings:

```javascript
const GEN_Y = {1:22, 2:6, 3:-10, 4:-24, 5:-36};
// Irmão/Irmã: x = -12 * siblings.length (cresce para a esquerda)
// Filho/a: y=-24, x centrado (spacing 12)
// Neto/a: y=-36
// Tio/Tia: z=10 (plano paralelo)
// Primo/a: z=10
```

**Regra:** `autoFocus = PEOPLE.length === 0 || isFocus` — o primeiro pessoa adicionado sempre é a Pessoa Foco.

### 5.3 Câmera

```javascript
camera.position.set(0, 22, 75);
camera.lookAt(0, 4, 0);
controls.target.set(0, 4, 0);
controls.minDistance = 14;
controls.maxDistance = 180;
```

---

## 6. Sistema de Vínculos / Bonds

### 6.1 Tipos de vínculos existentes

```javascript
const REL_BOND_TYPES = new Set([
  // Bowen clássicos
  'bowen_coesao', 'bowen_conflito', 'bowen_distancia', 'bowen_corte',
  // Relacionais genograma padrão
  'proximo', 'estreito', 'conflito', 'distante', 'desavenca', 'dominante', 'generico',
  // Gêmeos
  'gemeo', 'gemeo_identico'
]);
// Vínculos conjugais (roteados para drawMarriage, NÃO para drawBowen):
// 'casamento', 'separacao', 'divorcio'
// Vínculos de filiação (roteados para drawFilicao):
// 'filho', 'adotado', 'fostered', 'biologico'
```

### 6.2 Função de roteamento `drawAllBonds()`

```javascript
function drawAllBonds() {
  // 1. Casamentos (drawMarriage → genLayer)
  BONDS.forEach(b => {
    if (!['casamento','separacao','divorcio'].includes(b.type)) return;
    // ... drawMarriage() → genLayer.push(...objs)
  });
  // 2. Filiação (genLayer)
  // ... agrupar por casal → drawFilicao()
  // 3. Relacionais (drawBowen → bowenLayer)
  BONDS.forEach(b => {
    if (!REL_BOND_TYPES.has(b.type)) return;
    const nA=nodeMap[b.a], nB=nodeMap[b.b]; if (!nA||!nB) return;
    bowenLayer.push(...drawBowen(nA.mesh.position.clone(), nB.mesh.position.clone(), b.type));
  });
}
```

### 6.3 `drawBowen(posA, posB, type)` — representações 3D

| Tipo | Representação |
|---|---|
| `bowen_coesao` | Tubo duplo verde espesso |
| `bowen_conflito` | Zigzag vermelho |
| `bowen_distancia` | Linha pontilhada/tracejada laranja |
| `bowen_corte` | Linha cinza com X |
| `proximo` | 2 tubos paralelos verdes finos |
| `estreito` | 3 tubos paralelos verdes finos |
| `conflito` | Zigzag vermelho |
| `distante` | Pontilhado vermelho |
| `desavenca` | Arco + barras T nas pontas |
| `dominante` | Arco + cone-seta na ponta B |
| `generico` | Tubo único cinza |
| `gemeo` | Arco baixo (y-3) sem marcação |
| `gemeo_identico` | Arco baixo + barra vertical central |

### 6.4 `drawMarriage(posA, posB, isSep, minGen, isDiv=false)`

- Casamento: tubo duplo paralelo horizontal  
- Separação (`isSep=true`): + 1 barra diagonal vermelha no centro  
- Divórcio (`isDiv=true`): + 2 barras diagonais vermelhas (offset ±0.4)

### 6.5 Adição via menu de contexto

```javascript
function ctxAddBond(type) {
  hideCtxMenu();
  refreshBondSelects();
  const typeEl = document.getElementById('bond-type');
  if (typeEl) typeEl.value = type;
  const bA = document.getElementById('bond-a');
  if (bA && ctxPersonId) bA.value = ctxPersonId;
  updateBondUI();
  document.getElementById('bond-modal').removeAttribute('hidden');
}
```

---

## 7. Menu de Contexto (Botão Direito)

HTML com submenu CSS puro (hover):

```html
<div id="ctx-menu">
  <div class="ctx-name" id="ctx-name">—</div>
  <div class="ctx-sep"></div>
  <div class="ctx-item ctx-sub">
    <span>🔗 Adicionar relação</span>
    <span class="ctx-sub-arrow">▶</span>
    <div class="ctx-submenu">
      <div class="ctx-item" onclick="ctxAddBond('casamento')">⊏⊐ Casamento</div>
      <div class="ctx-item" onclick="ctxAddBond('separacao')">⊏╱⊐ Separação</div>
      <div class="ctx-item" onclick="ctxAddBond('divorcio')">⊏╳⊐ Divórcio</div>
      <div class="ctx-sep"></div>
      <div class="ctx-item" onclick="ctxAddBond('proximo')">=  Próximo</div>
      <div class="ctx-item" onclick="ctxAddBond('estreito')">≡  Estreito</div>
      <div class="ctx-item" onclick="ctxAddBond('conflito')">W  Conflito</div>
      <div class="ctx-item" onclick="ctxAddBond('distante')">··· Distante</div>
      <div class="ctx-item" onclick="ctxAddBond('desavenca')">⊣⊢ Desavença</div>
      <div class="ctx-item" onclick="ctxAddBond('dominante')">→  Dominante</div>
      <div class="ctx-item" onclick="ctxAddBond('generico')">—  Genérico</div>
      <div class="ctx-sep"></div>
      <div class="ctx-item" onclick="ctxAddBond('gemeo')">⌒  Gêmeo</div>
      <div class="ctx-item" onclick="ctxAddBond('gemeo_identico')">⌒| Gêmeo Idêntico</div>
    </div>
  </div>
  <div class="ctx-sep"></div>
  <div class="ctx-item" onclick="ctxEdit()">✏️ Editar / complementar ficha</div>
  <div class="ctx-item" onclick="ctxSetFocus()">⊙ Definir como pessoa foco</div>
  <div class="ctx-item" id="ctx-expand" onclick="ctxExpandGen()">⊕ Expandir genograma</div>
  <div class="ctx-sep"></div>
  <div class="ctx-item danger" onclick="ctxRemove()">✕ Remover pessoa</div>
</div>
```

Reveal do submenu via CSS puro:
```css
.ctx-sub .ctx-submenu { display: none; }
.ctx-sub:hover .ctx-submenu { display: block; }
```

---

## 8. Modal "+ Pessoa" — Lógica Inteligente

### 8.1 `openAddModal()` — context-aware

```javascript
function openAddModal() {
  const hasFocus = PEOPLE.find(p => p.focus);
  
  if (!hasFocus) {
    // PRIMEIRA PESSOA: modo "Quem é você?"
    title.textContent = 'Quem é você?';
    hint.style.display = 'block';           // "Esse é você — pessoa central..."
    relRow.style.display = 'none';          // sem "Relação com pessoa foco"
    genRow.style.display = 'none';          // sem "Geração"
    focusRow.style.display = 'none';        // sem checkbox "Definir como foco"
    partRow.style.display = 'none';         // sem "Vínculo conjugal"
    document.getElementById('add-focus').checked = true;  // sempre foco
  } else {
    // DEMAIS PESSOAS: formulário completo
    title.textContent = 'Adicionar ao genograma';
    // ... mostra todos os campos
    refreshPartnerSelect();
    refreshBondSelects();
    onRelChange(document.getElementById('add-rel').value);
  }
  document.getElementById('add-modal').removeAttribute('hidden');
}
```

### 8.2 IDs de elementos críticos no modal

| ID | Elemento |
|---|---|
| `add-modal` | Container do modal (hidden attr) |
| `add-modal-title` | H3 do título |
| `add-focus-hint` | Parágrafo hint "pessoa central" |
| `add-name` | Input nome |
| `add-gender` | Select gênero |
| `add-birth` | Input ano nascimento |
| `add-dec` | Select falecido/a |
| `add-rel` | Select relação com foco |
| `add-gen` | Select geração |
| `add-focus` | Checkbox "definir como foco" |
| `add-partner` | Select vínculo conjugal |
| `add-rel-row` | Label wrapper de add-rel |
| `add-gen-row` | Label wrapper de add-gen |
| `add-focus-row` | Label wrapper do checkbox |
| `add-partner-row` | Label wrapper de add-partner |

---

## 9. Animação — `animate()`

```javascript
function animate() {
  aniId = requestAnimationFrame(animate);
  const t = clock.getElapsedTime();

  // Float + rotação: pessoas vivas
  PEOPLE.forEach(d => {
    const e = nodeMap[d.id];
    if (!e || d.deceased) return;
    e.mesh.position.y = d.y + Math.sin(t * .8 + e.mesh._floatOff) * .14;
    e.mesh.rotation.y = t * (d.focus ? 0.18 : 0.12) + e.mesh._floatOff * .3;
    e.mesh.rotation.x = Math.sin(t * .5 + e.mesh._floatOff) * .04;
  });

  // Spin: nós eco
  ECO_NODES.forEach(d => {
    const e = nodeMap[d.id];
    if (!e) return;
    e.mesh.position.y = d.y + Math.sin(t * .6 + e.mesh._floatOff) * .1;
    e.mesh.rotation.y = t * .4;
  });

  // Pulso no anel (TorusGeometry) da Pessoa Foco
  const fp = PEOPLE.find(p => p.focus);
  if (fp) {
    const fe = nodeMap[fp.id];
    if (fe) {
      const ring = fe.mesh.children.find(c =>
        c.geometry && c.geometry.type === 'TorusGeometry'
      );
      if (ring && ring.material)
        ring.material.emissiveIntensity = .4 + Math.sin(t * 1.4) * .3;
    }
  }

  controls.update();
  renderer.render(scene, camera);
  updateLabels();
  updateExtClusterLabels();
}
```

**Nota:** `_floatOff` é atribuído aleatoriamente a cada `mesh` no momento da criação (`mesh._floatOff = Math.random() * Math.PI * 2`), garantindo que cada nó tenha fase de animação diferente.

---

## 10. Geometrias e Materiais

| Tipo de nó | Geometry | Material | Cor base |
|---|---|---|---|
| Homem vivo | `BoxGeometry(2.6, 2.6, 2.6)` | `MeshPhysicalMaterial` | `#4a9eff` |
| Mulher viva | `SphereGeometry(1.5, 32, 32)` | `MeshPhysicalMaterial` | `#ff7eb3` |
| Homem falecido | `BoxGeometry` | `MeshPhysicalMaterial` | `#aaa` + X interno |
| Mulher falecida | `SphereGeometry` | `MeshPhysicalMaterial` | `#aaa` + X interno |
| Pessoa Foco | Qualquer + | `TorusGeometry` filho | anel `#ffd700` |
| Nó eco (genérico) | `OctahedronGeometry(1.8)` | `MeshPhysicalMaterial` | por categoria |
| Casamento (tubo) | `TubeGeometry(CatmullRomCurve3)` | `MeshStandardMaterial` | `#ffd700` |
| Separação (slash) | `TubeGeometry` | `MeshStandardMaterial` | `#f87171` |

---

## 11. Sistema de Camadas (Layer Toggle)

```javascript
function applyLayers() {
  const genON  = document.getElementById('layer-gen').checked;
  const ecoON  = document.getElementById('layer-eco').checked;
  const bowON  = document.getElementById('layer-bow').checked;
  const labON  = document.getElementById('layer-lab').checked;

  genLayer.forEach(o   => o.visible = genON);
  ecoLayer.forEach(o   => o.visible = ecoON);
  bowenLayer.forEach(o => o.visible = bowON);
  ecoMeshes.forEach(o  => o.visible = ecoON);
  // labels: CSS class toggle
}
```

**Regra crítica:** Qualquer objeto 3D adicionado à cena DEVE ser registrado no array correto (`genLayer`, `bowenLayer`, `ecoLayer` / `ecoMeshes`) ou nunca responderá ao toggle de camadas.

---

## 12. Configuração Supabase

```javascript
const SUPA_URL = 'https://wnsufourebpvgikkvuig.supabase.co';
const SUPA_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Induc3Vmb3VyZWJwdmdpa2t2dWlnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODg3MDAzMTMsImV4cCI6MjEwNDI3NjMxM30.L4W6gdLj0l4Y_e2hz4pU3T9E0vkMR-B2hvf0KIAg-0Y';
```

### 12.1 Schema relevante (LGPD-compliant)

```sql
-- ELOS NÃO é prontuário → não sujeito ao CFM 2.299/2021
-- Conformidade apenas com LGPD

CREATE TABLE elos_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  cpf_hash TEXT,           -- CPF nunca em plaintext
  lgpd_accepted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE elos_genogramas (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES elos_users(id),
  title TEXT,
  data JSONB,              -- snapshot de PEOPLE + BONDS + ECO_NODES + ECO_BONDS
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- RLS habilitado em TODAS as tabelas ELOS
```

---

## 13. Tela Inicial e Navegação

### 13.1 Welcome screen (botões atuais)

```html
<button class="btn-build" onclick="startNewGenogram()">🔨 Construir meu genograma</button>
<button class="btn-primary" onclick="enterDemo()">Demo: Sofia</button>
<button class="btn-sec" onclick="showAuth()">Entrar com conta</button>
```

**REMOVIDO nesta conversa:** "Demo: Família Santos-Ferreira" e toda a função `runComplexDemo()` (~110 linhas).

### 13.2 Topbar

```html
<div class="tb-brand" onclick="goHome()" title="Voltar à tela inicial" style="cursor:pointer">⬡ ELOS</div>
<button class="build-btn" onclick="goHome()" title="Voltar à tela inicial">⌂ Início</button>
<button class="build-btn" onclick="startNewGenogram()">🔨 Novo</button>
```

### 13.3 `goHome()`

```javascript
function goHome() {
  document.getElementById('welcome').classList.remove('gone');
}
// NÃO limpa a cena — o genograma em construção permanece
```

---

## 14. Demo "Sofia"

`enterDemo()` → `runSofiaDemo()` — popula `PEOPLE`, `BONDS`, `ECO_NODES`, `ECO_BONDS` com dados de exemplo e chama `voiceBuild()`.

Este é o **benchmark de qualidade visual** para validar animações, posicionamento e vínculos.

---

## 15. `populateBlFamList()` — Título dinâmico

```javascript
function populateBlFamList() {
  const fp = PEOPLE.find(p => p.focus);
  if (!fp) return;
  const parts = (fp.name || '').trim().split(/\s+/);
  const sobrenome = parts.length > 1 ? parts[parts.length - 1] : parts[0];
  document.getElementById('bl-fam-title').textContent = `Família ${sobrenome}`;
}
// Nunca hardcode "Família Andrade" ou qualquer sobrenome fixo.
```

---

## 16. Histórico de Bugs Corrigidos

| Bug | Causa | Fix |
|---|---|---|
| "Família Andrade" hardcoded | Título fixo no HTML | `populateBlFamList()` dinâmico |
| UBS Cabanga invisível | `confirmAddService()` não registrava em `ecoMeshes`/`ecoLayer` | Adicionado push nos arrays corretos |
| Modal mostrando campos errados na 1ª pessoa | `openAddModal()` sem context-awareness | Lógica `hasFocus` para simplificar |
| Genograma cramped | Coordenadas pequenas (10×) | Escala 2.5× + câmera z=75 |
| Demo auto-iniciando | `setTimeout(runComplexDemo, 800)` em `main()` | Removido |
| Ícones sem rotação (estáticos) | `animate()` não aplicava rotation.y | Adicionado rotation.y + rotation.x + ring pulse |
| 2 sistemas de posição divergentes | `voiceBuild()` e `confirmAdd()` usavam coords diferentes | `confirmAdd()` espelha `FIXED_POS` |

---

## 17. Funções Principais — Índice Rápido

| Função | Responsabilidade |
|---|---|
| `main()` | Entry point: inicializa Three.js, cena, controles |
| `animate()` | Render loop: float, rotação, ring pulse |
| `voiceBuild()` | Constrói cena a partir de PEOPLE/BONDS/ECO_NODES |
| `buildPerson(d)` | Cria mesh 3D de uma pessoa |
| `buildEcoNode(d)` | Cria mesh 3D de um nó eco |
| `drawAllBonds()` | Roteia e desenha todos os vínculos |
| `drawMarriage(posA,posB,isSep,minGen,isDiv)` | Vínculos conjugais 3D |
| `drawBowen(posA,posB,type)` | Vínculos relacionais 3D |
| `openAddModal()` | Abre modal de pessoa (context-aware) |
| `confirmAdd()` | Salva nova pessoa e reconstrói cena |
| `ctxAddBond(type)` | Abre bond-modal pré-preenchido via context menu |
| `applyLayers()` | Toggle visibilidade por camada |
| `enterDemo()` / `runSofiaDemo()` | Carrega demo de exemplo |
| `goHome()` | Retorna à welcome sem limpar cena |
| `showAuth()` | Exibe modal de login/cadastro |
| `populateBlFamList()` | Título "Família X" dinâmico |
| `updateLabels()` | Sincroniza labels CSS2D com posições 3D |

---

## 18. Convenções de Desenvolvimento

1. **Nunca extrair CSS ou JS para arquivos externos** — tudo inline no HTML
2. **Registrar todo objeto 3D em seu array de camada** antes de adicionar à cena
3. **Espelhar `FIXED_POS`** em qualquer função que posicione pessoas manualmente
4. **Não reintroduzir o botão/função `runComplexDemo`** — foi removido intencionalmente
5. **Não hardcodar sobrenomes** em títulos de família
6. **`_floatOff`** deve ser atribuído a todo novo mesh de pessoa/eco para animação independente
7. **`isDiv` flag** em `drawMarriage` para divórcio (2 barras vermelhas vs 1)
8. **RLS em todas as tabelas Supabase ELOS** — nunca desabilitar

---

## 19. Próximos Passos Sugeridos

- [ ] Exportar genograma como imagem (Three.js renderer.domElement.toDataURL)
- [ ] Salvar/carregar genograma via Supabase (serializar PEOPLE + BONDS + ECO)
- [ ] Timeline 3D: adicionar eixo temporal ao eixo Z
- [ ] Ficha clínica completa por pessoa (expandir modal de edição)
- [ ] Modo colaborativo (dois clínicos editando ao mesmo tempo)
- [ ] Impressão/exportação PDF do ecomapa
- [ ] Validação LGPD: fluxo de consentimento ao criar conta

---

## 20. Links e Referências

- **Deploy Netlify:** https://elos-genograma.netlify.app *(verificar URL atual)*
- **Supabase Dashboard:** https://supabase.com/dashboard/project/wnsufourebpvgikkvuig
- **Three.js r128 Docs:** https://threejs.org/docs/index.html?q=
- **Referência genograma símbolos:** McGoldrick, M. (2008). *Genograms: Assessment and Intervention*
- **Teoria Bowen:** Kerr & Bowen (1988). *Family Evaluation*

---

*Gerado em sessão Claude (Cowork) — Mestrado Saúde Coletiva — ELOS v19*
