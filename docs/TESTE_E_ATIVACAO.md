> Estado atual: a versão 0.4 operacional está descrita em [FREQUENCY_V2_CANDIDATE.md](FREQUENCY_V2_CANDIDATE.md). Este documento preserva o histórico do marco anterior; as menções a coleta/agenda compartilhada/fila como futuras foram substituídas pela entrega candidata. A ativação real aguarda revisão, merge e publicação autorizados.

# Roteiro de teste e ativação do Coletor

## Amanhã: o que já pode ser testado

1. Manter a única pasta 0.3 funcional na Área de Trabalho. A 0.4 ainda não deve
   substituí-la: a janela desktop normal bloqueia uso até ativação institucional.
2. Se quisermos demonstrar o parser da 0.4, extrair o ZIP inteiro em uma pasta
   privada de teste fora da Área de Trabalho. Confirmar manifesto/commit/hash do
   relatório de entrega; não usar HTML real de alunos.
3. A pessoa técnica inicia a prévia separada com
   `programa/python.exe -B -m coletor --preview-server --port 8765` e abre
   `http://127.0.0.1:8765`. Usar somente “Usar dados de exemplo”. Conferir versão
   0.4.0, tabela fictícia, filtros e “Envio desativado”. Essa prévia de
   desenvolvimento não libera o desktop, não faz login nem cria chave.
4. Fechar a aba e encerrar o processo de prévia. A demonstração não agenda,
   coleta ou envia dados. Não há launcher separado para ela nesta entrega.

## Antes de testar o login real

| Etapa | Ação | Barreira |
| --- | --- | --- |
| Dashboard | Responsável viabiliza leitura autenticada de “Deploy to production OFF”. | O APPROVAL_PLAN manda parar se setting/evidência estiver inacessível; não alterar toggle para contornar. |
| Banco | Repetir preflight somente leitura e aplicar as duas migrations novas com hashes aprovados. | DDL autorizado, mas aguarda readback; sem repair/replay do histórico. |
| Acesso servidor | Aprovar e configurar COLLECTOR_DB dedicado e papel com USAGE no schema collector_auth e SELECT/INSERT/UPDATE nas quatro tabelas. | Binding/role/grants exigem aprovação específica. Nunca fallback PROD_DB. |
| Cifra servidor | Aprovar e configurar COLLECTOR_REFRESH_KEY, 32 bytes aleatórios em base64url sem padding, exclusivo da cifra. | Nunca SESSION_SECRET ou segredo no ZIP/PC; não gerar nem expor chave nesta preparação. |
| Publicação | Autorizar merge/deploy das PRs e ativar COLLECTOR_ENABLED=true após gates. | PRs continuam draft; CI aprovado não autoriza publicação. OFFICIAL_ORIGIN deve ser https://admin.escolaieda.com. |
| Microsoft | Operador valida próprio User.Read, auth_time, accountEnabled, marcador de revogação e grupo ADMIN. | Falta/null/403 bloqueiam; consentimento ou segurança adicional exigem confirmação própria. Não ampliar permissões. |
| PC | Responsável confirma cada primeira criação de chave persistente. | TPM é padrão; Software KSP exige escolha adicional. QA anônimo não comprova TPM/persistência real. |

Usar a credencial técnica Web existente. Não criar certificado novo ou permissão
ampla para contornar configuração incompleta. A Biblioteca preserva o ZIP antigo;
apenas o pacote validado do novo SHA é a versão corrente da mesma entrega.

## Depois da ativação autorizada

1. Entrar pelo programa; aceitar conscientemente o vínculo do PC. Digitar no
   navegador oficial o código mostrado no programa e confirmar a autorização.
   A senha permanece no navegador; nenhum refresh Microsoft vai para o PC.
2. Fechar e reabrir: o mesmo vínculo deve renovar online sem login ordinário
   repetido. Se o backend/provedor falhar, operações devem permanecer bloqueadas.
3. Cancelar um pedido antes de concluir: nenhum acesso deve ser liberado. Uma
   conclusão sem claim do PC não autoriza comandos e expira com limpeza servidor.
4. Testar Sair da conta: apagar chave local e retirar vínculo servidor. Sem rede,
   a chave local deve ser apagada e a saída servidor fica pendente; concluir a
   retirada pelo navegador quando a conexão voltar. Não declarar revogação remota
   concluída sem prova. Fechar o programa não equivale a Sair da conta.
5. Somente após esses resultados discutir substituir a pasta 0.3. Envio continua
   desativado; captura real de aluno e integração produtiva têm escopo próprio.

O preparo usa fixtures sintéticas e CNG anônimo. Não criamos credencial real,
alteramos produção ou usamos dados de alunos para obter evidência de teste.

## Remoção portátil após o uso

Fechar a janela conserva o vínculo para reabrir depois. Para retirar o acesso
antes de excluir a pasta, feche o Coletor e execute **Remover acesso deste PC.cmd**,
confirmando a ação. O equivalente técnico é
`programa/python.exe -B -m coletor --safe-removal`.

O comando não instala/desinstala software nem apaga arquivos do programa ou
preferências. Usa a chave gerenciada desse perfil Windows para retirar somente
o dispositivo correspondente; outros PCs e outras chaves não são removidos.
A exclusão manual da pasta não é interceptada e não limpa a chave por si só.

Com rede, aguarde a confirmação de retirada remota e remoção da chave local.
Sem rede, a saída pode remover a chave local e retornar código 2: guarde o UUID
público e o link `/frequency-collector/revoke?device=...` mostrado, para retirar
esse dispositivo no Ecossistema quando a rede voltar. O registro público fica
nos dados locais; remover a pasta não garante fila nem conclusão automática.
Se a limpeza local falhar (código 1), preserve a pasta e resolva antes de removê-la.
Código 0 confirma limpeza ou ausência de vínculo registrado; neste último caso,
o comando informa que nenhuma chave foi verificada ou apagada.
