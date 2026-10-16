# Instaladores Windows — cinco últimas versões

Esta pasta mantém os **cinco instaladores .exe mais recentes aprovados pelos testes Windows** após novas integrações na branch main. O processo começa a funcionar quando o workflow da PR #7 for integrado. Os nomes contêm a versão da aplicação, o número do build e o identificador do commit, mesmo que a versão nominal (por exemplo, 0.4.0) não mude.

- **Baixar:** abra o arquivo .exe nesta pasta pelo GitHub, usando a opção de baixar o arquivo completo. Ele é armazenado no **Git LFS**, não como código de texto. Ao clonar o repositório, instale Git LFS e execute git lfs pull para obter os executáveis. Não tente executar um arquivo de ponteiro LFS.
- **Verificar:** cada .exe possui um arquivo .exe.sha256. O versoes.json registra nome, versão, hash SHA-256, commit original e execução de CI.
- **Retenção:** ao publicar a sexta versão validada, a mais antiga deixa de aparecer nesta pasta, mas seus dados históricos podem continuar contabilizados no Git LFS. A remoção da pasta **não equivale à eliminação do histórico de armazenamento LFS**.
- **Segurança:** somente o job Windows do workflow Preview checks aprovado na main autoriza a publicação. O empacotamento usa o instalador Inno Setup real e o teste de instalação/desinstalação no Windows. O publicador nunca executa o .exe recebido.
- **Compatibilidade:** instalador Windows x64, instalado por usuário, com Windows 10 ou superior e os pré-requisitos especificados em docs/WINDOWS_INSTALLER.md (WebView2, Edge e .NET Framework 4.8). A validação automatizada não substitui a homologação com a conta Microsoft, o Smecel e PCs físicos da escola.
- **Assinatura:** o script de compilação assina o .exe apenas se os segredos de assinatura estiverem configurados. Sem eles, o instalador continuará sendo um executável Windows válido, mas pode exibir avisos do SmartScreen; não declarar a assinatura como concluída nesses casos.

O commit automático é feito com o GITHUB_TOKEN e **não dispara um segundo build**. A publicação precisa de contents: write e de autorização da proteção da branch main para esse token. Se a política impedir push direto, o job falhará **sem apagar a última versão publicada**; um administrador terá de autorizar um mecanismo compatível com a proteção da branch.

Documentação complementar: docs/WINDOWS_INSTALLER.md.
