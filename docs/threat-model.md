# Threat Model

## Escopo

Este documento cobre os riscos principais do gateway e coordinator no fluxo de criação, execução e submissão de jobs.

## Ativos críticos

- Saldo e cobrança de clientes.
- Integridade de resultados de jobs.
- Disponibilidade dos endpoints de inferência e submissão.
- Reputação e identidade de workers.

## Ameaças e mitigações

### 1) Fraude de resultados

**Ataque**
- Worker envia resultado inválido para receber pagamento.
- Worker tenta manipular payload de submit para burlar verificação.

**Mitigações**
- Assinatura Ed25519 obrigatória sobre `assignment_id + nonce + output_hash`.
- Verificação de nonce por assignment para impedir troca de contexto.
- Validação estrita do payload (`extra=forbid`, limites de tamanho, campos mutuamente exclusivos).
- Pipeline de verificação com marcação de `verified/rejected/disputed` e ajuste de reputação.

### 2) Replay

**Ataque**
- Reenvio de submissão antiga para duplicar recompensa.
- Reuso de assinatura válida em outro assignment.

**Mitigações**
- `nonce` único por assignment e comparação obrigatória no submit.
- Rejeição de assignment já submetido (`409`).
- Assinatura inclui `assignment_id` e `nonce`, inviabilizando replay cruzado.

### 3) Spam / DoS de API

**Ataque**
- Alto volume de requests no gateway para degradar serviço.
- Flood de `/jobs/submit` por worker comprometido.

**Mitigações**
- Rate limiting no gateway por API key e por IP (janela deslizante).
- Rate limiting no coordinator por worker para submit.
- Limites de payload no gateway (`text <= 20k`, `texts <= 32`, `item <= 10k`) e no submit do coordinator.
- Timeout e cancelamento de jobs no gateway para evitar polling infinito.

### 4) Sybil (múltiplas identidades de worker)

**Ataque**
- Operador cria múltiplos workers para capturar mais jobs/receita e manipular consenso.

**Mitigações**
- Worker vinculado a owner autenticado e chave pública própria.
- Reputação e histórico por worker com penalidade para comportamento ruim.
- Possibilidade de regras operacionais adicionais: stake mínimo, KYC opcional, limites por owner/IP/faixa de rede.

## Controles operacionais recomendados

- Rotação periódica de tokens internos e API keys.
- Alertas para picos de `429`, `401`, e erros de assinatura.
- Dashboards com taxa de disputa, rejeição e fraude por worker/owner.
- Auditoria periódica das políticas de limite e thresholds de reputação.
