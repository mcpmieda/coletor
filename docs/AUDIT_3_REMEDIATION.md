# Revalidação da issue #3 — 13/10/2026

Base reproduzida: `6fc048960fe5314f3a2b5066bd175746de5acc40`, PR #1 ainda aberta
e draft; `main` contém o README inicial. A correção usa branch isolada derivada
da implementação da #1 e PR empilhada contra `feat/preview-diario-anual`.
Não houve merge, release, instalação produtiva, login, coleta ou envio real.
Todos os dados de teste são gerados sinteticamente.

## Matriz de achados

| ID | Veredicto no head auditado | Tratamento e prova nesta correção | Limite / pendência |
| --- | --- | --- | --- |
| AUD-001 | Falha real na separação de confiança futura. A fixture limpa gerava 2 upserts com recibo falso. | `validate_for_transmission` bloqueia toda transmissão nesta versão; sintéticos possuem bloqueio adicional. Testes cobrem recibo aparentemente completo e `source_format` adulterado, com hash recalculado. Serviço/ponte continuam sem método de envio. | Adaptador autenticado e verificação servidor-lado não existem. Não são implementados para satisfazer a auditoria; precisam de contrato e autorização próprios antes de qualquer ativação. |
| AUD-002 | Falha real: UI/serviço 8 MiB, parser 16 MiB, transporte 10 MiB. Fixture densa de 32 fichas excedeu o serviço. | Um JSON compartilhado governa HTML (24 MiB), transporte (48 MiB + 64 KiB), 64 fichas, 130 mil registros, 200 mil nós e mil diagnósticos. Regressão de 64 fichas passa no serviço; excesso de bytes/nós/registros continua bloqueado. A UI informa o tamanho do arquivo rejeitado. | Teto defensivo não promete compatibilidade com qualquer diário/PC. Escapes podem exceder o orçamento de transporte, com rejeição explícita. Medidas abaixo são sintéticas. |
| AUD-003 | Melhoria de extensibilidade, sem corrupção demonstrada nas amostras de seis posições. | Cardinalidade suportada continua explicitamente em seis. Regressões 4/5/7 rejeitam o cabeçalho e mantêm transmissão bloqueada; seis permanece coberto. | Ampliação por modalidade exige novo contrato observado. Nenhum DDL/contrato acadêmico foi alterado; item triado para evolução futura. |
| AUD-004 | Erro real da UI: deduplicação por mensagem escondia fichas distintas. | União deduplica apenas cópias exatas do diagnóstico; resumo conta diagnósticos/fichas, detalhes mostram referência/data/aula, filtro e páginas de 20. Testes com duas fichas e 25 diagnósticos. | Parser já agrega por código/ficha e retém a primeira localização. Não anunciamos contagem exata de eventos. Nomes ficam fora dos detalhes/logs. |
| AUD-005 | Advisory confirmado na fonte oficial; versões 3.2.7 afetadas. | Vitest/mocker atualizados para 4.1.11 com lockfile regenerado; `npm ci`, testes, lint, tipos/build e `npm audit` verificados. | Escopo desenvolvimento; não foi demonstrada exploração no desktop. SCA é fotografia do momento. |
| AUD-006 | Configuração real: `main protected=false`, required checks off, rulesets vazio. API somente leitura em 13/10/2026. | Proposta mínima abaixo; workflow ganha também `push` em main como defesa secundária. | **Pendente de autorização administrativa específica e disponibilidade no plano GitHub. Alterar workflow não resolve proteção de branch.** |
| AUD-007 | Lacuna de automação; não prova vulnerabilidade por cada ferramenta ausente nem ausência de controles externos. | CI adiciona Ruff (sintaxe/erros), ESLint (regras básicas e eval), Bandit (regras perigosas selecionadas), Gitleaks com redação e histórico, auditorias npm produção/dev e Python runtime/teste; cobertura mínima de 80% nas três regras sensíveis. | Não equivale a auditoria completa ou habilitação de CodeQL/secret scanning/push protection na plataforma. Configurações externas permanecem intactas e dependem de diagnóstico/autorização próprios. |
| AUD-008 | Erro real: duas instâncias sobrescreviam a mesma revisão 1 sem aviso. | Lock SO entre processos em sidecar persistente, comparação de revisão sucessora e gravação atômica. Corrida de dois processos: um salva, outro recebe conflito. Ponte retorna conflito; UI preserva erro e permite recarregar. | Escopo desktop no mesmo perfil/arquivo; navegador continua com armazenamento próprio. Sem sincronização entre máquinas. Lock falha fechado se não adquirido; SO libera após encerramento. |
| AUD-009 | Defesa em profundidade real, sem compromisso demonstrado. Python oficial já tinha hash; manifesto já tinha versões/hashes finais. | Actions fixadas nos SHAs oficiais das versões usadas; dependências Windows e ferramentas de build ganham hashes PyPI antecipados; pip exige hashes e não usa build isolation para baixar dependências não fixadas. Gitleaks também tem hash antecipado. | O lock aceita os artefatos publicados da versão exata, escolhidos conforme plataforma. O job Windows deve comprovar resolução/build final. npm preserva integrity; manifesto final continua obrigatório. Ferramentas de análise dev estão fixadas por versão, não têm lock transitivo completo. |
| AUD-010 | Melhoria real: abort de HTTP/ponte não assegura interrupção do parser. Estado nativo já mantém leitura enquanto há trabalho. | Alternativa prevista no achado: “Descartar resultado”, sem prometer cancelamento. UI mantém busy/controles bloqueados até conclusão e descarta resposta tardia; guarda contra duas leituras. Teste renderizado com promise nativa pendente. QA de bandeja mantém estado real durante descarte. | Não implementa cancelamento cooperativo nem scheduler. Encerramento nativo continua coberto pelo CI Windows. |

Nenhum dos dez itens estava integralmente resolvido no SHA original. A issue #2
continua independente: sem inventar regra de total mensal, identidade N→1 ou
integração produtiva para obter checks verdes.

## Reprodução e medições

Reprodução do SHA original, em checkout temporário isolado: fixture limpa gera
2 registros no payload sob recibo falso; segunda instância aceita novamente a
revisão 1 e sobrescreve o horário. Regressões no head corrigido proíbem ambos.

Windows x64, Python 3.14.7, um processo novo por caso; fixtures densas geradas
por `scripts/measure_synthetic_volume.py`, sem relatório real. Pico é working
set do processo (incluindo Python/árvore/snapshot/serialização); não é benchmark
completo da janela WebView nem projeção de todo computador da escola.

| Fichas | HTML bytes | Pedido JSON bytes | Registros | Segundos parser | JSON snapshot bytes | Pico working set bytes |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 32 | 9.374.522 | 9.860.760 | 64.128 | 2,183 | 7.103.657 | 150.564.864 |
| 40 | 11.718.042 | 12.325.808 | 80.160 | 2,968 | 8.883.929 | 181.239.808 |
| 50 | 14.647.442 | 15.407.118 | 100.200 | 3,427 | 11.109.271 | 220.774.400 |
| 64 | 18.748.602 | 19.720.952 | 128.256 | 4,424 | 14.224.747 | 274.149.376 |

## AUD-006: proposta administrativa, não aplicada

Nomes reais dos checks do workflow: `verify` e `windows-portable`, emitidos por
GitHub Actions (App ID `15368`), confirmados no CI do SHA original.
Configuração mínima para `main`: PR obrigatória; ambos os checks com origem
GitHub Actions e branch atualizada; conversas resolvidas; force-push e exclusão
bloqueados; aplicar também a administradores; sem novas exceções.

Para um mantenedor único, **zero aprovações humanas obrigatórias no gate GitHub**
evita exigir que o autor aprove a própria PR, o que não pode satisfazer a regra.
Isso mantém o requisito de revisão independente como evidência desta auditoria;
não equivale ao aceite original de uma aprovação humana obrigatória. Quando um
segundo revisor humano com write estiver disponível e autorizado, subir para 1.
Não tornar CodeRabbit um check obrigatório sem confirmar que produz um check
de aprovação utilizável — a PR draft original foi apenas ignorada pelo bot.

Rota possível após confirmação específica: REST
`PUT /repos/mcpmieda/coletor-frequencia-smecel/branches/main/protection` pela CLI
GitHub já autenticada. Leitura atual retorna `permissions.admin=true`; isso não
garante plano elegível. O repositório é privado; proteção para privados exige
plano compatível. Não mudar visibilidade, plano, permissões ou bypass para contornar.

Payload proposto (somente documentação):

```json
{
  "required_status_checks": {
    "strict": true,
    "checks": [
      {"context": "verify", "app_id": 15368},
      {"context": "windows-portable", "app_id": 15368}
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 0,
    "require_last_push_approval": false
  },
  "restrictions": null,
  "required_linear_history": false,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
```

Após configuração aprovada: reler a regra e verificar PR válida / rejeição de
checks falhos e push direto em teste administrativo autorizado. Nenhum teste
de escrita em main foi feito nesta entrega.

## Fontes e critério de encerramento

Validação local desta correção: 120 testes Python; 60 testes UI; lint, tipos e
build; cobertura 90% conjunta em parser/validação/configurações (mínimo 80%);
SCA npm/Python sem vulnerabilidades conhecidas nos conjuntos consultados;
Bandit selecionado sem achados; Gitleaks em 18 commits sem achados após triagem
de um falso positivo. A única exceção do scanner é o valor literal exato do
namespace público de localStorage `coletor-smecel.fox.v1`, sem exceção ampla por
arquivo/regra/commit. Probes sintéticas confirmaram que SAST e scanner retornam
falha para violações controladas. QA renderizado no Edge headless cobriu telas
1440×1000, 1240×820 e 390×844, fichas distintas nos detalhes e descarte de resultado
nativo tardio; sem exceções de página. A janela nativa/pacote final dependem do
job Windows do novo SHA, não deste teste headless.

- [Issue #3](https://github.com/mcpmieda/coletor-frequencia-smecel/issues/3).
- [Advisory oficial Vitest/mocker](https://github.com/advisories/GHSA-82fw-gwwq-j7x9), consultado em 13/10/2026.
- [Proteção e disponibilidade por plano](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).
- [REST branch protection](https://docs.github.com/en/rest/branches/branch-protection).

Encerramento continua bloqueado enquanto houver requisito material pendente:
AUD-006 administrativo, decisão explícita sobre itens triados, review independente
do head corrigido e CI completo desse SHA (incluindo Windows portátil/nativo).
Sucesso local não substitui esses gates. A publicação é PR draft, sem merge.
