# pkg-installer.elf — contrato do payload próprio

Payload próprio do projeto `send_pkg-payload`.

Caminho esperado pelo app:

```text
payloads/pkg-installer.elf
```

Porta esperada no PS5:

```text
9328
```

Endpoints esperados:

```text
GET /health
GET /status
POST /upload?name=arquivo.pkg
GET /install?path=/data/pkgs/arquivo.pkg&name=Nome
```

Contrato validável:

- `/health` deve responder imediatamente com `service=ps5-send-pkg-payload-installer`, `version>=14` e feature `upload`;
- `/status` deve responder JSON real;
- `/upload` é o fluxo padrão do app para PKG;
- `/upload` exige `Content-Length`, recebe bytes `application/octet-stream` e grava em `/data/pkgs/<name>`;
- `name` deve ser basename `.pkg`, sem barras, sem `..`, sem caractere de controle e sem byte não ASCII;
- o arquivo recebido é gravado primeiro como `.part` e promovido por `rename` ao final do upload completo;
- depois do upload completo, o payload dispara a instalação em thread própria e mantém `/status` como fonte de estado;
- `/install` fica preservado para PKG que já exista no PS5 e aceita somente caminhos `.pkg` em `/data/`, `/user/data/` ou `/mnt/usb`;
- caminhos contendo `..` são rejeitados;
- antes de instalar, `/data/...` é reescrito internamente para `/user/data/...`;
- tenta DPI local próprio `127.0.0.1:9040`;
- se DPI falhar, tenta `sceAppInstUtilInstallByPackage`;
- se falhar, tenta `sceAppInstUtilAppInstallPkg` como último fallback diagnóstico;
- grava status em `/data/ps5_send_pkg_payload/last-install.json`;
- grava log diagnóstico em `/data/ps5_send_pkg_payload/pkg-installer.log`.

Correção v3:

- remove escalonamento kernel no boot do payload;
- abre `/health` e `/status` antes de qualquer tentativa de instalação;
- só chama APIs de instalação depois que `/install` é acionado;
- mantém o serviço ativo em `0.0.0.0:9328`.


## v7

- Porta temporária/própria de teste: `9328`.
- Endpoint adicional: `GET /shutdown` para encerrar a instância nova sem reiniciar o PS5.

## v12

- Endpoint principal de PKG passa a ser `POST /upload?name=arquivo.pkg`.
- O app não usa etaHEN, DPI_v2 externo nem FTPsrv para instalar PKG.
- O payload próprio recebe, persiste e instala o PKG com código do próprio projeto.

## v13

- Corrige a espera do DPI embutido para cobrir o timeout interno de inicialização do próprio DPI.
- Preserva o diagnóstico de boot/conexão do DPI em vez de limpar a informação depois da porta abrir.
- Testa variações controladas de URI/caminho no `sceAppInstUtilInstallByPackage`.
- Aceita `sceAppInstUtilAppInstallPkg` com retorno `0` como instalação concluída, em vez de marcar como erro `icon_only_not_final`.
- Inclui `sceAppInstUtilInitialize` no diagnóstico quando a instalação falha.

## v14

- Adiciona marcador explícito `pkg-installer v14 http-upload endpoint:/upload` usado pelo log de boot e pela validação do ELF.
- `/health` passa a declarar os endpoints disponíveis, incluindo `/upload`, para evitar validação dependente de string otimizada pelo compilador.
- O app passa a exigir `pkg-installer` `v14` como versão mínima compatível.
