# Aion 2 Weed Metter 🌿⚔️

<p align="center">
  <img src="app_icon.ico" alt="Aion 2 Weed Metter Logo" width="96" height="96">
</p>

<p align="center">
  <strong>Overlay DPS Meter em tempo real de altíssima performance para o MMORPG Aion 2.</strong><br>
  Captura nativa de tráfego de rede (Packet Sniffing assíncrono), leitura oficial de combate, suporte completo a Grupos e Raids, HUD transparente com aceleração gráfica e design moderno.
</p>

<p align="center">
  <a href="https://github.com/igors1lva/Aion-2-Weed-Metter/releases/latest"><img src="https://img.shields.io/github/v/release/igors1lva/Aion-2-Weed-Metter?color=10b981&label=Release&logo=github" alt="Release"></a>
  <img src="https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-0078d7?logo=windows" alt="Platform">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776ab?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License">
  <img src="https://img.shields.io/badge/Anti--Cheat-100%25%20Safe%20(No%20Injection)-brightgreen" alt="Safe">
</p>

---

## 🌟 Visão Geral

O **Aion 2 Weed Metter** foi arquitetado especificamente para suprir as necessidades de jogadores competitivos de PvE e PvP no Aion 2. Ao contrário de ferramentas invasivas baseadas em injeção de memória (DLL hooking), o Weed Metter atua de maneira **100% passiva e indetectável**, capturando e decodificando diretamente os pacotes de rede UDP/TCP do protocolo de jogo através da biblioteca Npcap.

Com interface compacta de **360px** inspirada no design oficial do Questlog, ele fornece métricas instantâneas de dano individual, DPS da Party/Raid, Combat Power (CP), temporizador de enfurecimento (Berserk), Time to Death (TTD) estimado com ícone de caveira e contador de mortes por membro do grupo.

---

## ✨ Principais Funcionalidades

### 🖥️ 1. HUD Dual-Layer com Transparência Nativa
- **Camada de Fundo (60% translúcida)**: Barras temáticas por classe com bordas arredondadas e efeito de vidro escuro, integrando-se perfeitamente ao cenário do jogo.
- **Camada de Frente (100% sólida/opaca)**: Textos, nomes, ícones de classe, porcentagens e valores de DPS com nitidez cristalina, sem desbotar ou sofrer distorção.
- **Largura Exata de 360px**: Dimensionado milimetricamente para se alinhar com o HUD nativo do jogo e o Questlog.

### 🛡️ 2. Identificação Rigorosa e Autêntica do Jogador
- **Zero Suposições Especulativas**: Ao abrir o medidor dentro de um mapa aberto, ele permanece em standby neutro (`- | Aguardando identificar jogador`) sem atribuir erroneamente outros players ou membros do grupo ao seu perfil.
- **Reconhecimento Oficial**: Identifica o personagem local no instante em que ele se materializa no mundo via pacotes oficiais do servidor (`MyCharAppear_NT` / `Login_RS`), sincronizando automaticamente seu nome, ícone de classe e Combat Power (CP).
- **Personalização Rápida**: Clique com o botão direito do mouse no HUD para definir ou renomear seu personagem manualmente a qualquer momento.

### ⚔️ 3. Rastreamento Preciso de Party e Raid
- **Detecção Multiclasse de Raid**: Diferencia ataques em lutas de Boss mesmo quando múltiplos jogadores compartilham a mesma classe (ex: 2 Rangers, 2 Chanters).
- **Eliminação de Fantasmas**: Filtra o combate estritamente para membros confirmados do grupo/raid, descartando jogadores aleatórios do mundo aberto.
- **Preservação de Histórico de Luta**: Ao finalizar um Boss de Dungeon, o relatório final da luta permanece visível na tela até o início do próximo combate, mesmo se a equipe sair da dungeon.

### 💀 4. Painel de Chefe, TTD e Berserk Timer
- **HP do Chefe em Tempo Real**: Monitora o monstro/boss ativo com barra de vida percentual atualizada pacote a pacote.
- **Time to Death (TTD)**: Exibe o ícone de caveira vermelha 💀 seguido do tempo estimado até a derrota do Boss baseado no DPS médio constante do grupo.
- **Enrage / Berserk Timer**: Sincronizado com o relógio do servidor através de pacotes de tempo (`MapFrame_NT`), alertando a contagem regressiva antes do monstro entrar em modo berserk.

### 🩸 5. Contador de Mortes & Efeito Striped Gray
- **Contador de Mortes (💀 N)**: Registra com exatidão quantas vezes cada integrante foi abatido na luta.
- **Barra Listrada / Apagada**: Enquanto o jogador estiver caído, sua barra assume tonalidade cinza com listras diagonais translúcidas, restaurando a cor vibrante da classe imediatamente ao reviver.

### ⚡ 6. Suporte a Frame Generation & Atalho Global F8
- **Modo Click-Through (F8)**: Pressione a tecla **F8** a qualquer instante para travar a interface e permitir cliques transparentes diretamente sobre o medidor, ideal para rotações frenéticas sem acidentalmente arrastar ou focar o medidor.
- **Compatibilidade AFMF / Lossless Scaling / DLSS 3**: Renderização otimizada para evitar quebras de canal alfa ou stuttering causados por geradores de quadros.

---

## 🎨 Paleta de Classes

| Classe | Cor Primária | Hex |
| :--- | :--- | :--- |
| **Gladiator** | Vermelho Carmesim | `#8b263e` |
| **Templar** | Azul Aço / Cobalto | `#1e3a8a` |
| **Assassin** | Verde Esmeralda Escuro | `#065f46` |
| **Ranger** | Verde Folha / Jade | `#15803d` |
| **Sorcerer** | Roxo Místico | `#6b21a8` |
| **Elementalist** | Roxo Ametista | `#581c87` |
| **Spiritmaster**| Azul Violeta Profundo | `#4c1d95` |
| **Cleric** | Dourado Âmbar | `#b45309` |
| **Chanter** | Bronze / Mostarda Nobre | `#854d0e` |
| **Fighter** | Laranja Terracota | `#c2410c` |

---

## 📥 Instalação e Execução

### Opção 1: Executável Pronto (Recomendado)
1. Baixe a versão mais recente em [**Releases**](https://github.com/igors1lva/Aion-2-Weed-Metter/releases).
2. Baixe e instale o driver de captura de rede **Npcap** oficial (caso ainda não possua):
   - [Download Npcap](https://npcap.com/#download)
   - *Nota: Durante a instalação do Npcap, marque a opção "Install Npcap in WinPcap API-compatible Mode".*
3. Extraia o arquivo `Aion2_Weed_Metter_v1.0.zip` em qualquer pasta.
4. Execute o arquivo **`INICIAR_METER.bat`** ou clique com o botão direito em **`Aion2_Weed_Metter.exe`** e selecione **"Executar como Administrador"**.

---

### Opção 2: Executar a partir do Código Fonte (Python)
Se preferir rodar diretamente via código:

```bash
# 1. Clone o repositório
git clone https://github.com/igors1lva/Aion-2-Weed-Metter.git
cd Aion-2-Weed-Metter

# 2. Instale as dependências
pip install -r requirements.txt

# 3. Inicie o medidor (requer permissão de Administrador no terminal)
python aion2_overlay.py
```

---

## 🛠️ Como Compilar o Executável (.exe)

O projeto inclui o arquivo de especificação pronto para o PyInstaller:

```bash
# Instale o PyInstaller se necessário
pip install pyinstaller

# Gere o executável standalone de alta performance
pyinstaller Aion2_DPS_Meter.spec --noconfirm
```
O executável compilado será gerado na pasta `dist/Aion2_Weed_Metter.exe`.

---

## 🕹️ Controles e Atalhos

| Atalho / Ação | Função |
| :--- | :--- |
| **F8** | Alterna o modo **Click-Through** (Trava cliques / Permite clicar através do HUD). |
| **Clique com Botão Esquerdo + Arrastar** | Move a janela pela tela do jogo (quando destravada). |
| **Clique Simples na Barra** | Alterna entre a visualização de **Dano por Jogador** e **Dano por Habilidade**. |
| **Clique com Botão Direito** | Abre a janela para **definir ou alterar manualmente o nome do personagem**. |
| **Botão 📊** | Alterna o modo de visualização. |
| **Botão 🔄** | Reseta o combate e limpa métricas de dano atuais. |
| **Botão ⏸** | Pausa / Retoma a leitura do medidor. |
| **Botão 🔓 / 🔒** | Alterna o bloqueio de movimentação do HUD. |
| **Botão ✕** | Fecha e encerra o aplicativo com segurança. |

---

## 🔬 Protocolo de Rede e Opcodes do Aion 2

O motor do Weed Metter monitora os pacotes trocados entre o cliente e o servidor do jogo, tratando descompressão LZ4 em tempo real:

- **`13824 (MapFrame_NT)`**: Sincronização do timestamp oficial do servidor para o cálculo de Enrage/Berserk.
- **`13845 (Login_RS)`**: Relação de personagens vinculados à conta ao carregar o jogo.
- **`13857 (PrepareEnterMap_NT)`**: Sinaliza transição de mapa ou entrada em instância de Dungeon.
- **`13875 (MyCharAppear_NT)`**: Inicialização do jogador local no mapa (Nome, Classe, Key, Combat Power).
- **`13893 (CharAppear_NT)`**: Detecção de outros jogadores e membros no campo de visão.
- **`13910 (CharCombatPowerUpdate_NT)`**: Atualização em tempo real do Combat Power (CP) do jogador.
- **`14040 / 14050 (SkillCast_NT / SkillHit_NT)`**: Eventos de uso de habilidades, acertos, dano bruto e efeitos.
- **`14141 (CharWarpEnter_NT)`**: Conclusão de teleporte no mundo.

---

## 📄 Licença

Distribuído sob a licença **MIT**. Consulte o arquivo [`LICENSE`](LICENSE) para obter mais informações.

Desenvolvido com carinho por **[Igor Silva (igors1lva)](https://github.com/igors1lva)** para a comunidade de Aion 2.
