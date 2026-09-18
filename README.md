# Restaurante por quilo — registro de consumo (v1)

Aplicação desktop **Windows** em **Python + PySide6** que identifica a comanda pelo código de barras,
lê o peso na balança **Toledo Prix 3 Fit** (protocolo **Prt5**), calcula o valor e registra o consumo.
Banco: SQLAlchemy (SQLite por padrão; MySQL 8 por configuração).

## Como executar

**Windows (plataforma-alvo)** — instale Python 3.13 64 bits e dê dois cliques em `run_windows.bat`.

**macOS/Linux (só desenvolvimento)**
```bash
./run.sh
```

Na primeira execução a balança está em **modo simulado** e o banco é criado com dados de demonstração:

| Operador   | PIN  | Observação                      |
|------------|------|---------------------------------|
| Operador 1 | 1111 | atendimento                     |
| Gerente    | 9999 | autoriza a alteração de preço/kg |

Comandas de teste: `000154` (aberta, com bebida + sobremesa = R$ 20,00, o exemplo do documento),
`000155` (aberta, vazia), `000156` (fechada). Digite o código e Enter, como faria o leitor.

Roteiro rápido: comanda `000154` → **Prato vazio (360 g)** → **Aplicar tara** → **Prato + comida (860 g)**
→ o painel mostra `0,500 kg` e `R$ 39,95` → **Registrar consumo** → **Confirmar**. Total: `R$ 59,95`.

## Configuração
Arquivo `config.json` em `~/.balanca_restaurante/` (Windows: `C:\Users\<você>\.balanca_restaurante\`).
Também dá para alterar pelo botão **Balança** da tela principal.

- **Balança real:** modo `serial`, porta (`COM3`...), baudrate igual ao **C15** da balança, 8 bits, sem paridade, 1 stop bit.
- **MySQL:** `database_url` = `mysql+pymysql://usuario:senha@servidor/restaurante` (ou variável `DATABASE_URL`).
- **Outra pasta de dados:** variável `BALANCA_HOME`.

## Estrutura
```
main.py                     ponto de entrada
app/hardware/prt5.py        montagem/interpretação dos pacotes Prt5 (funções puras)
app/hardware/prix3fit.py    driver (usa qualquer objeto com a API do pyserial)
app/hardware/simulator.py   balança simulada que fala Prt5 byte a byte
app/hardware/scale.py       contrato Scale (troca de modelo sem mexer no resto)
app/services/               regras: comandas, preços, estabilidade do peso, autenticação
app/database/               modelos SQLAlchemy, conexão, dados iniciais
app/ui/                     tema, telas e a thread de leitura da balança
tests/                      protocolo, regras de negócio e fluxo completo da tela
```

## Testes
```bash
.venv/bin/python -m pytest        # Windows: .venv\Scripts\python -m pytest
```
Cobrem os exemplos literais do manual da Toledo, as regras RN001–RN008 e o fluxo da tela sobre a balança simulada.
Rodam sem hardware e em qualquer sistema.

## Decisões de projeto
- **Dinheiro e peso sempre em `Decimal`**; arredondamento `ROUND_HALF_UP` (RN003). `float` é rejeitado.
- **O total é sempre recalculado no serviço**, com o preço vigente; a tela nunca envia valor pronto.
- **Peso só é aceito estável** após 3 leituras válidas e iguais (configurável); instável, negativo e sobrecarga bloqueiam o registro.
- **Confirmação obrigatória** antes de gravar. Enter (inclusive o do leitor) nunca aciona botões dos diálogos.
- **Um prato não é registrado duas vezes**: só rearma quando o prato sai da balança (peso zero/negativo) ou outra comanda é lida.
- **Cancelar não apaga**: fica marcado como cancelado com motivo, data e operador (RN005).
- **Preço em tabela própria** com vigência: alterar o preço não muda consumos antigos (RN006). Exige PIN de gerente (RF019).
- O `raw_response` (bytes hexadecimais) de cada pesagem é guardado para auditoria.
- A balança só devolve o peso do display; o **bruto** só é gravado quando a tara foi enviada pelo sistema.

## Validação pendente no Windows e com a balança real
Este código foi desenvolvido e testado num Mac, com a balança simulada. Antes de usar de verdade:

1. Rodar `run_windows.bat` e a suíte de testes no Windows 10/11.
2. Conferir o visual em Windows (fonte Segoe UI, escala de tela 125%/150%).
3. Descobrir a porta COM no Gerenciador de Dispositivos (adaptador USB-RS232) e testar em **Balança → Testar conexão**.
4. Na balança: C13 = Serial (ou USB, firmware ≥ 9.30), C14 = Prt5, C15 = mesma velocidade da tela (C14/C15 exigem a senha técnica).
5. Conferir com a balança física: resposta ao `ENQ`, ACK/NACK da tara e do preço, e se `IIIII` aparece de fato durante a acomodação.
6. Conferir se a tara enviada por software permanece memorizada entre pesagens (o manual não detalha).
7. Empacotar com PyInstaller **no Windows** (não dá para gerar o .exe a partir do Mac).

## Fora do escopo da v1
Cadastro de produtos e usuários, relatórios, backup, monitoramento da balança e estoque/caixa (MVP 3 do documento).
