# Restaurante por quilo — servidor, autoatendimento, caixa e operador (v2)

Aplicação desktop **Windows** em **Python + PySide6** para restaurante de comida por quilo com a balança
**Toledo Prix 3 Fit** (protocolo **Prt5**). Funciona em rede local com **um PC servidor** e quantos terminais forem necessários
(um ou mais autoatendimentos, caixa, operador).

## Como funciona

```
                     PC SERVIDOR (modo "servidor")
                     guarda os dados · aceita os terminais · mostra IP e código
                     também pode abrir o Caixa/Operador neste mesmo PC
                                 ▲
        ┌────────────────────────┼─────────────────────────┐
        │ rede local (HTTP)      │                         │
 PC AUTOATENDIMENTO 1     PC AUTOATENDIMENTO 2       PC CAIXA / AUTOPAGAMENTO
 balança + impressora     (opcional, mais um)        leitor + impressora (+ TEF)
 + leitor de código       ...
```

O terminal **pergunta o IP e o código do servidor** na primeira vez e a partir daí conversa com ele; a balança, a impressora e o
leitor de código de barras continuam ligados no PC do próprio terminal.

**Fluxo do cliente:**
1. No autoatendimento o cliente informa o **CPF**; o sistema cria a comanda, **imprime** (código de barras + CPF mascarado) e já
   abre a **tela de pesagem**, sem precisar ler a comanda de novo.
2. Ele pesa o prato (a balança dá o peso líquido) e marca bebidas/sobremesas. Se voltar depois (outro prato, sobremesa), basta
   **ler a comanda** no autoatendimento.
3. Na saída, **lê a comanda no caixa** (ou informa o CPF, se a perdeu), confere e **paga**: manual (operador) ou autopagamento (TEF).

Ciclo da comanda: `OPEN` → `AWAITING_PAYMENT` (enviada ao caixa) → `PAID`; também existe `CANCELLED`.

### Os módulos (`--modo`)
| Modo | Onde | O que faz |
|---|---|---|
| `servidor` | PC principal | Guarda o banco, aceita os terminais, mostra **IP e código**, lista quem está conectado e abre Caixa/Operador. |
| `autoatendimento` | PC da balança | CPF, comanda impressa, pesagem, bebidas/sobremesas, "perdi minha comanda". Tela cheia e botões grandes. |
| `caixa` | PC de saída | `checkout.mode = manual`: operador registra o pagamento (dinheiro com troco, PIX, crédito, débito, parcial). `auto`: o cliente paga sozinho no TEF. |
| `operador` | qualquer | Atendimento assistido: nova comanda, pesagem, lançamentos, cancelamentos, enviar ao caixa, reabrir, **produtos e preços** (PIN de gerente). |

## Como executar

Serve para testar tudo num único computador (balança simulada, impressão em PDF) e é o mesmo comando usado em produção.
Use **Python 3.13** (64 bits); o 3.14 não foi testado com o PySide6.

### Windows 10/11
1. Instale o Python 3.13 em python.org e marque **"Add python.exe to PATH"** e **"py launcher"**.
2. Na pasta `balanca_app`, dê dois cliques no atalho do módulo que quer abrir:

| Atalho | Módulo |
|---|---|
| `iniciar_servidor.bat` | servidor (abra este primeiro) |
| `iniciar_autoatendimento.bat` | autoatendimento (cliente) |
| `iniciar_caixa.bat` | caixa / autopagamento |
| `iniciar_operador.bat` | operador |

Na primeira execução o atalho cria o ambiente virtual e instala as dependências (precisa de internet, leva alguns minutos).
Pelo PowerShell, dá para passar opções: `.\run_windows.bat --modo autoatendimento --janela`.

### macOS (desenvolvimento e testes)
1. Instale o Python 3.13: `brew install python@3.13`.
2. Na pasta `balanca_app`, rode (na primeira vez ele cria o ambiente e instala tudo):
```bash
./run.sh --modo servidor
```
3. Em **outro terminal**, abra os demais módulos, por exemplo:
```bash
./run.sh --modo autoatendimento --janela
```
Se o `run.sh` criar o ambiente com um Python diferente do 3.13 e a instalação falhar, recrie com o 3.13:
```bash
rm -rf .venv && /opt/homebrew/bin/python3.13 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

### Opções da linha de comando
| Opção | Efeito |
|---|---|
| `--modo servidor\|autoatendimento\|caixa\|operador` | qual módulo abrir (sem ela, o programa pergunta) |
| `--checkout manual\|auto` | caixa com operador ou autopagamento pelo cliente |
| `--abrir caixa\|operador` | no modo servidor, já abre esta tela junto |
| `--janela` | não abre em tela cheia (útil para testar) |

### Testar num computador só (passo a passo)
1. Abra o **servidor** e deixe a janela aberta. Ela mostra a **porta** e o **código de acesso**.
2. Abra o **autoatendimento** (`--janela` no Mac). Na pergunta "Onde estão os dados?", deixe **Em outro PC** e informe
   IP `127.0.0.1`, a porta e o código do servidor; clique em **Testar conexão** e **Salvar**. A escolha fica gravada.
3. Informe um CPF válido (ex.: `529.982.247-25`): a comanda é criada, o PDF da comanda é gerado em
   `~/.balanca_restaurante/tickets/` e a pesagem abre direto. Use a janela **Simulador da balança** para pôr peso no prato.
4. Para pagar, clique em **Abrir caixa** na janela do servidor (login: Operador 1 / PIN 1111) e leia o código da comanda.

Sem servidor, escolha **Neste PC** na pergunta acima: tudo roda em um só programa, sem rede.

### Rodar os testes
```bash
.venv/bin/python -m pytest          # Windows: .venv\Scripts\python -m pytest
```

### Se algo não abrir
- **Servidor indisponível:** o servidor precisa estar aberto antes; confira IP, porta e código.
- **"NÃO INICIOU" na janela do servidor:** a porta 8765 já está em uso (outro servidor aberto). Feche-o ou mude `server.port` no `config.json`.
- **Erro inesperado:** os detalhes ficam em `erros.log`, na pasta de dados (`~/.balanca_restaurante/` no Mac,
  `C:\Users\<você>\.balanca_restaurante\` no Windows).

## Instalar em dois (ou mais) PCs

**Em todos os PCs:** Python 3.13 (64 bits) e a pasta `balanca_app`. Os atalhos `.bat` criam o ambiente na primeira execução.

**1. PC servidor** — dê a ele um **IP fixo** (ou reserva no roteador) e abra `iniciar_servidor.bat`.
A janela mostra o **endereço** (ex.: `192.168.0.10 : 8765`) e o **código de acesso** (8 caracteres). Deixe-a aberta.
Na primeira vez o Windows pergunta se libera o programa na rede: **permita em redes privadas**. Se preferir liberar a porta na mão
(PowerShell como administrador):
```powershell
netsh advfirewall firewall add rule name="Restaurante Servidor" dir=in action=allow protocol=TCP localport=8765 profile=private
```
Para usar o caixa nesse mesmo PC, clique em **Abrir caixa** na janela do servidor.

**2. Cada terminal** — abra `iniciar_autoatendimento.bat` (ou `iniciar_caixa.bat`). Na primeira vez aparece
"Onde estão os dados deste computador?": deixe **Em outro PC**, digite o **IP** e o **código** do servidor, clique em
**Testar conexão** e **Salvar**. Para mudar depois: launcher → *Conexão com o servidor…*.

**3. Vários kiosks:** repita o passo 2 em cada PC de autoatendimento. Cada um aparece na lista do servidor pelo nome
(`autoatendimento@NOME-DO-PC`). Códigos de comanda nunca se repetem entre eles.

Sem configurar nada, o programa roda **num único PC** (modo "neste PC", com balança simulada) — bom para conhecer e testar.
Operadores de demonstração: **Operador 1 / 1111** e **Gerente / 9999**. Comandas de teste: `000154` (aberta, R$ 20,00),
`000155` (vazia), `000156` (já paga). Sair do autoatendimento/autopagamento em tela cheia: **Ctrl+Shift+Q** + PIN de gerente.

### Segurança da rede — leia
- O servidor só atende quem apresenta o **código de acesso**. Trate-o como uma senha (dá para gerar outro na janela do servidor).
- A comunicação é **HTTP sem criptografia**: use só em **rede local confiável**; **nunca exponha a porta à internet**.
  PINs, CPFs e valores trafegam em claro pela rede do restaurante. Se houver Wi-Fi de clientes, mantenha os terminais em outra rede.
- Nenhum SQL trafega pela rede: o terminal só chama as operações permitidas (lista fixa em `app/net/protocol.py`).

### Produtos e preços (gerente)
No módulo **operador**, o botão **Produtos** (PIN de gerente) abre o cadastro: **novo produto** (por unidade, código gerado
automaticamente), **alterar preço**, **renomear** e **desativar/ativar**. O botão **Preço/kg** continua como atalho para a comida por quilo.
- Preço novo vale a partir de agora; o histórico é guardado e comandas já lançadas **não mudam**.
- Desativar tira o produto do autoatendimento sem apagar as vendas antigas. A comida por quilo não pode ser desativada.
- Os terminais pegam produtos e preços novos na próxima pesagem, sem reiniciar.
- O **PIN de gerente é conferido no servidor** a cada alteração (não só na tela), e 5 erros seguidos travam a checagem por 30 s.
  Outras ações (cancelar lançamento, reabrir comanda, receber pagamento) ainda podem ser feitas por qualquer operador.
- PINs de demonstração: **Operador 1 = 1111**, **Gerente = 9999**. Ainda não há tela para trocá-los: troque antes de usar de verdade.

### Banco de dados
Fica **só no servidor**, em SQLite (`C:\Users\<você>\.balanca_restaurante\balanca.db`): não precisa instalar nada. Faça **backup**
copiando esse arquivo com o servidor fechado. Se um dia precisar de MySQL, ele é configurado **apenas no servidor** (launcher →
*Conexão…* → *Banco de dados deste PC…*); os terminais não mudam.

## Configuração por PC (`config.json`)
| Chave | Padrão | Significado |
|---|---|---|
| `role` | `""` | modo deste PC (`servidor`, `autoatendimento`, `caixa`, `operador`); vazio = perguntar |
| `connection.mode/host/port/access_key` | — | onde estão os dados (`remote` = servidor em outro PC) |
| `server.port` / `server.access_key` | 8765 / gerado | porta e código do servidor |
| `scale.mode` | `simulated` | `serial` para a balança real; `port`/`baudrate` iguais ao **C15** da balança |
| `kiosk.require_cpf` | `true` | CPF obrigatório para abrir comanda |
| `kiosk.block_duplicate_cpf` | `true` | não cria comanda se o CPF já tem outra **em aberto sem pagar** (em atendimento ou aguardando pagamento); `false` permite várias |
| `kiosk.auto_tare` | `true` | envia a tara padrão do prato (`scale.default_tare_g`) ao iniciar a pesagem |
| `kiosk.auto_register_after_s` | `0` | `0` = cliente toca em REGISTRAR PRATO; `N` = registra sozinho após N s de peso estável |
| `kiosk.idle_timeout_s` | `90` | sem toque, volta ao início (a comanda continua aberta) |
| `checkout.mode` | `manual` | `manual` (operador) ou `auto` (cliente paga no TEF) |
| `checkout.gateway` | `simulated` | `simulated` ou `tef` (ver abaixo) |
| `printing.printer_name` | `""` | `""` = só gera PDF (seguro p/ testes); `"@default"` = impressora padrão do Windows; ou o nome exato |
| `printing.paper_width_mm` | `80` | largura da bobina |
| `printing.print_on_start` / `print_receipt` | `true` | imprime a comanda ao abrir / o comprovante ao pagar |

Pasta de dados: `C:\Users\<você>\.balanca_restaurante\` (mude com a variável `BALANCA_HOME`). Erros inesperados vão para `erros.log` lá.

## Impressão
Usa o sistema de impressão do Windows (`QPrinter`): serve qualquer impressora instalada, inclusive térmicas de 80 mm com driver.
A comanda sai com **código de barras Code 128**, data/hora e CPF **mascarado** (`***.982.247-**`). Sem impressora configurada, gera PDF em
`~/.balanca_restaurante/tickets/`. **Não há suporte ESC/POS direto** (comandos crus da térmica).

## Pagamento
- **Manual:** o operador escolhe a forma, informa o valor (parcial ou total; dinheiro calcula troco) e registra. Cartão/PIX aceitam NSU/ID.
- **Automático (autopagamento):** o cliente lê a comanda ou informa o CPF e escolhe PIX/crédito/débito; a cobrança passa por
  `app/payments/gateway.py`. Hoje só existe o **TEF simulado**. **A integração com o TEF real NÃO está feita**: depende do fornecedor
  (Sitef, PayGo, Stone, Cielo...), do SDK e da homologação com a adquirente. O ponto de encaixe é `TefGateway.charge()` em `app/payments/tef.py`.
- Se o cartão for cobrado mas a gravação falhar, o NSU é anotado em `pagamentos_pendentes.log` e o cliente é orientado a chamar um atendente.

## CPF e privacidade (LGPD)
O CPF só serve para recuperar a comanda perdida; aparece mascarado em tickets e listas e está gravado **em texto** na tabela `command`
do servidor. Defina prazo de retenção e quem acessa o servidor; se não precisar do CPF depois do pagamento, apague-o.

## Estrutura
```
main.py                         entrada (--modo, --checkout, --abrir, --janela)
app/net/                        protocol (contrato), server (HTTP embutido), client (proxy dos serviços)
app/hardware/                   balança: prt5, prix3fit, simulator, scale
app/services/                   regras: command_service (comandas, CPF, pagamentos), pricing, weighing, auth
app/payments/                   gateway TEF (simulado + ponto de integração) e executor em thread
app/printing/                   ticket (modelo), barcode (Code 128), printer (QPrinter/PDF)
app/database/                   modelos SQLAlchemy, conexão, migrações, dados iniciais
app/ui/                         server_window, kiosk_window, selfcheckout_window, cashier_window, main_window (operador)...
tests/                          protocolo, regras, CPF/pagamento, rede, impressão e fluxo das telas
```

## Testes
```bash
.venv/bin/python -m pytest        # Windows: .venv\Scripts\python -m pytest
```
169 testes, sem hardware e em qualquer sistema. Cobrem: exemplos literais do manual da Toledo, regras de negócio, CPF, pagamentos
(troco, parcial, misto, recusa), migração de banco antigo, **servidor e terminais por HTTP (inclusive dois kiosks + caixa ao mesmo
tempo, código errado, servidor fora do ar)**, impressão em PDF e o fluxo completo das telas.

## O que NÃO foi validado (faça antes de usar de verdade)
1. **Rede entre PCs de verdade.** Os testes usam servidor e terminais na **mesma máquina** (localhost). Firewall do Windows, IP fixo, Wi-Fi
   e latência real não foram exercitados.
2. **Windows.** Desenvolvido e testado num Mac: falta conferir instalação, fonte/escala de tela, porta COM e empacotamento (PyInstaller, só no Windows).
3. **Balança real** (respostas ao `ENQ`, ACK/NACK da tara, se a tara enviada persiste entre pesagens) e **leitura do código de barras
   impresso** com o seu leitor (conferi o desenho no PDF, não com um leitor).
4. **Impressora real** e **TEF real** (ver acima).
5. Toque em tela sensível de verdade: os botões são grandes, mas não testei em touchscreen.
6. **Vários kiosks:** a pesagem grava o texto bruto da balança, mas **não identifica qual kiosk/balança** a fez (o campo `scale_id` fica vazio).

## Decisões de projeto
- **Dinheiro e peso em `Decimal`**, arredondamento `ROUND_HALF_UP`; o total é sempre recalculado no servidor.
- **Uma comanda não paga por CPF** (opção `kiosk.block_duplicate_cpf`, ligada por padrão): o kiosk oferece continuar a existente. Desligada, o caixa avisa quando o CPF tem várias comandas e o autopagamento pede a leitura da comanda impressa em vez de adivinhar. Código sequencial gerado com nova tentativa em caso de colisão entre terminais.
- **Bloqueio por linha** (`SELECT ... FOR UPDATE`) em lançamentos e pagamentos, para dois terminais não mexerem na mesma comanda ao mesmo tempo.
- O primeiro pagamento trava a comanda (`AWAITING_PAYMENT`); só reabre se não houver pagamento.
- Lançamentos do cliente são assinados por um operador técnico, inativo, "Autoatendimento".
- Peso só vale após 3 leituras estáveis e iguais; um prato não é registrado duas vezes (só rearma quando o prato sai da balança).
- Cancelar não apaga: fica marcado com motivo, data e operador.
- Se a rede cair, o terminal mostra "Sem conexão com o servidor" e segue funcionando quando ela volta; erros inesperados vão para `erros.log`.
