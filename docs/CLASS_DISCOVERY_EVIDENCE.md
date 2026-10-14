> Estado atual: a versão 0.4 operacional está descrita em [FREQUENCY_V2_CANDIDATE.md](FREQUENCY_V2_CANDIDATE.md). Este documento preserva o histórico do marco anterior; as menções a coleta/agenda compartilhada/fila como futuras foram substituídas pela entrega candidata. A ativação real aguarda revisão, merge e publicação autorizados.

# Entrada primeiro e escolha de turmas

Evidência fornecida pelo operador após login no navegador cloud em 13/10/2026,
21:24:19 UTC. Inspeção restrita à lista; nenhum link de alunos ou diário foi aberto.

## Contrato observado

- Fonte: https://www.smecel.com.br/sistema/escola/turmaListar.php.
- Título: Listar Turmas - Ano Letivo 2026.
- Contexto: SECRETARIA DE EDUCAÇÃO DE MEDEIROS NETO / ESCOLA IEDA ALVES DE OLIVEIRA MCPM.
- Tabela #tabelaTurmas, linhas #tbodyTurmas tr; células drag0,ordinal1,código2,nome3,etapa4,matriz5,turno6.
- Código do atributo de link vinculoAlunoExibirTurma.php?ct=... na mesma linha do nome. Esse link é lido como metadado e nunca aberto.
- Controle a[role=combobox] ANO LETIVO: 2026; opções turmaListar.php?ano=2026 e equivalentes2025/2024/2023.
- Busca: Digite o nome ou parte do nome de uma turma.
-15linhas visíveis,ordinais1–15,busca vazia,sem paginação observada. Isso não comprova todas as contas,anos ou escola.
- Espaço irregular antes de VESPERTINO observado. Normalizam-se espaços,sem reconstruir nomes por código/série/turno.

Turmas/códigos não são fixados no programa. Ano vem do título e controle ativo,
nunca de ct. Esta versão reconhece somente o contexto institucional evidenciado.
O identificador local deriva desse texto exibido e não é identidade escolar
autenticada nem recibo externo. Outro contexto é recusado sem apagar seleções.

## Fluxo0.3.0-teste

Escolha ano → autorize abertura/lista → Entrar no Smecel → login diretamente
no Edge → Carregar turmas → marque nomes → escolha uma turma marcada →
autorize prévia → Ler diário manualmente. Não se digita código. Carregar turmas
explicitamente evita adivinhar quando login/SSO terminou ou interromper senha.
Reconhecer a lista não comprova identidade da conta.

Só IDs escolhidos,ano,contexto não secreto e revisão são persistidos em
class-selection.json,separado de settings.json. Perfis por contexto/ano preservam
as escolhas anteriores. O último ano salvo é sugerido. Não guarda alunos,
senha,cookies,tokens,HTML ou estado autenticado.

Lista filtrada/parcial/vazia não é revogação: escolhas não observadas continuam
salvas,mas não disponíveis para ler. Marcar/desmarcar salva automaticamente as
escolhas visíveis,conservando as demais. Limpar seleção deste ano e contexto
remove também as pendentes. Lock do SO,revisão e escrita atômica protegem contra
conflito/falha. Corrupção não copia nem ecoa conteúdo arbitrário.

Antes de cada leitura,o worker relê a lista no ano solicitado,confere contexto
e disponibilidade,e só então abre diario_frequencia.php?ct=...&ano=... já conhecido.
Não abre vínculos/listas de alunos. Diário somente em memória; identidade e
completude não comprovadas; envio bloqueado incondicionalmente.

Isolamento,proxy por destino,TLS,EOF cooperativo,Job Object e limpeza/cancelamento
seguem MANUAL_SESSION_MILESTONE.md. Fixtures/QA usam turmas e alunos sintéticos.
A versão0.2.0 entregue não é alterada/substituída por pacote ainda não validado.
