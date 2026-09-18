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
1. No autoatendimento o cliente informa o **CPF**, o sistema cria a comanda e **imprime** (código de barras + CPF mascarado).
2. Ele se serve, volta ao autoatendimento, **lê a comanda**, pesa o prato (a balança dá o peso líquido) e marca bebidas/sobremesas.
3. Na saída, **lê a comanda no caixa** (ou informa o CPF, se a perdeu), confere e **paga**: manual (operador) ou autopagamento (TEF).

Ciclo da comanda: `OPEN` → `AWAITING_PAYMENT` (enviada ao caixa) → `PAID`; também existe `CANCELLED`.

### Os módulos (`--modo`)
| Modo | Onde | O que faz |
|---|---|---|
| `servidor` | PC principal | Guarda o banco, aceita os terminais, mostra **IP e código**, lista quem está conectado e abre Caixa/Operador. |
| `autoatendimento` | PC da balança | CPF, comanda impressa, pesagem, bebidas/sobremesas, "perdi minha comanda". Tela cheia e botões grandes. |
| `caixa` | PC de saída | `checkout.mode = manual`: operador registra o pagamento (dinheiro com troco, PIX, crédito, débito, parcial). `auto`: o cliente paga sozinho no TEF. |
| `operador` | qualquer | Atendimento assistido: nova comanda, pesagem, lançamentos, cancelamentos, enviar ao caixa, reabrir, alterar preço/kg (PIN de gerente). |

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

**macOS/Linux (só desenvolvimento):** `./run.sh --modo servidor` e, em outro terminal, `./run.sh --modo autoatendimento --janela`.

### Segurança da rede — leia
- O servidor só atende quem apresenta o **código de acesso**. Trate-o como uma senha (dá para gerar outro na janela do servidor).
- A comunicação é **HTTP sem criptografia**: use só em **rede local confiável**; **nunca exponha a porta à internet**.
  PINs, CPFs e valores trafegam em claro pela rede do restaurante. Se houver Wi-Fi de clientes, mantenha os terminais em outra rede.
- Nenhum SQL trafega pela rede: o terminal só chama as operações permitidas (lista fixa em `app/net/protocol.py`).

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
135 testes, sem hardware e em qualquer sistema. Cobrem: exemplos literais do manual da Toledo, regras de negócio, CPF, pagamentos
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
- **Uma comanda em aberto por CPF**; código sequencial gerado com nova tentativa em caso de colisão entre terminais.
- **Bloqueio por linha** (`SELECT ... FOR UPDATE`) em lançamentos e pagamentos, para dois terminais não mexerem na mesma comanda ao mesmo tempo.
- O primeiro pagamento trava a comanda (`AWAITING_PAYMENT`); só reabre se não houver pagamento.
- Lançamentos do cliente são assinados por um operador técnico, inativo, "Autoatendimento".
- Peso só vale após 3 leituras estáveis e iguais; um prato não é registrado duas vezes (só rearma quando o prato sai da balança).
- Cancelar não apaga: fica marcado com motivo, data e operador.
- Se a rede cair, o terminal mostra "Sem conexão com o servidor" e segue funcionando quando ela volta; erros inesperados vão para `erros.log`.
