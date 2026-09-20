# Relatório de Desenvolvimento — Laboratório 1: Web Scraping

**Portal escolhido:** ProgramaThor (`https://programathor.com.br`)
**Área/cargo pesquisado:** vagas de desenvolvimento em **Python**
**Arquivos entregues:** `coleta_vagas.py` (código-fonte), `vagas_programathor.csv` / `vagas_programathor.json` (dados), este relatório.

---

## 1. Escolha do portal e decisões iniciais

O ProgramaThor foi escolhido por três motivos práticos. Primeiro, as páginas de listagem e de detalhe são **renderizadas no servidor**: o HTML já chega completo, o que permite usar `requests` + BeautifulSoup sem depender de JavaScript. Segundo, a **paginação é por URL** (`/jobs-python?page=2`, `/jobs-python?page=3`…), com link *Next ›* explícito no HTML, o que torna a navegação além da primeira tela simples e verificável. Terceiro, a **faixa salarial é opcional** no anúncio — a maior parte das vagas não a divulga —, o que exercita exatamente o requisito de tratar campos ausentes sem gerar exceção.

Foram descartados portais como Catho, InfoJobs e LinkedIn por exigirem login, usarem carregamento dinâmico agressivo ou bloquearem robôs em `robots.txt`.

Decidiu-se coletar em **duas camadas**: a listagem fornece apenas os links das vagas; os campos (título, empresa, local, salário, requisitos) são extraídos da **página individual de cada vaga**, que é mais completa e estável que o card resumido da listagem.

## 2. Robots.txt e sitemap.xml

A verificação é feita pelo próprio programa, na Etapa 1, **antes de qualquer coleta** (função `verificar_robots_e_sitemap()`). O script baixa `https://programathor.com.br/robots.txt`, grava o conteúdo em `robots_programathor.txt`, extrai por regex todas as regras `Disallow:` e todas as declarações `Sitemap:`, e carrega as regras em um `RobotFileParser` (`urllib.robotparser`). Em seguida baixa o sitemap declarado (ou tenta o caminho padrão `/sitemap.xml`), trata o caso de **índice de sitemaps** (`<sitemapindex>`, que aponta para sub-sitemaps) e salva todas as URLs encontradas em `sitemap_programathor.txt`.

Antes de baixar a listagem, o programa chama `can_fetch()` para o caminho `/jobs` e **aborta a execução** se a coleta não for permitida; o mesmo teste é repetido individualmente para cada URL de vaga dentro do laço principal.

**Resultado da verificação.** O arquivo `robots.txt` do portal é curto e permissivo:

```
Sitemap: https://programathor.com.br/sitemap.xml
User-agent: *
Disallow: /admin/
Disallow: /user/
Disallow: /users/
Disallow: /company/
```

A regra `User-agent: *` vale para todos os robôs e há quatro diretórios bloqueados, todos ligados a áreas privadas: painel administrativo (`/admin/`), páginas de cadastro e perfil de candidatos (`/user/`, `/users/`) e área restrita de empresas (`/company/`). Não existe nenhuma regra `Allow`, e — o que importa para este trabalho — **nenhum bloqueio incide sobre `/jobs`**, que é justamente onde ficam a listagem e as páginas individuais das vagas. A coleta realizada está, portanto, integralmente dentro do que o portal autoriza, o que foi confirmado em tempo de execução: `can_fetch('/jobs')` retornou `True`.

Vale registrar uma distinção que só aparece na leitura atenta do arquivo: o bloqueio é de `/company/`, no singular, enquanto os links para o perfil público das empresas usam `/companies/`, no plural. Ainda assim, o script não visita esses perfis — apenas lê o nome da empresa a partir do texto da âncora presente na própria página da vaga —, de modo que a questão não chega a se colocar.

Ainda sobre `/companies/`: o cabeçalho de todas as páginas do portal contém `/companies/sign_in` e `/companies/sign_up`, cujo texto é "Como empresa". Um seletor ingênuo por `a[href*='/companies/']` captura esse link de login antes do perfil real e grava "Como empresa" como nome do anunciante em **todas** as linhas — foi exatamente o que aconteceu na primeira versão do script. A extração passou então a exigir que o `href` case com `/companies/<id numérico>`, o que descarta as páginas de autenticação e recupera o nome correto.

O `robots.txt` também declara explicitamente o sitemap em `https://programathor.com.br/sitemap.xml`, exatamente o mecanismo de *Sitemap Autodiscovery* discutido em aula: o robô descobre o mapa do site sem precisar adivinhar o caminho. O script segue essa declaração automaticamente, em vez de assumir o caminho padrão, e grava as URLs encontradas em `sitemap_programathor.txt`.

Além do `robots.txt`, adotaram-se as boas práticas discutidas em aula: `User-Agent` de navegador acrescido do sufixo `(projeto-academico-web-scraping)`, que identifica a origem da coleta, intervalo de 1,5 s entre requisições, `timeout` de 20 s e no máximo 3 tentativas por página. Registre-se que o `RobotFileParser` compara apenas o token anterior à primeira barra desse cabeçalho (`mozilla`); como a única regra do portal é `User-agent: *`, a verificação vale igualmente para qualquer robô. Nenhum dado pessoal de candidatos é coletado — apenas informações públicas do anúncio —, o que mantém a coleta fora do escopo sensível da LGPD.

## 3. Ferramentas e bibliotecas por etapa

| Etapa | Ferramenta | Papel |
|---|---|---|
| Verificação de robots/sitemap | `requests`, `urllib.robotparser`, `re` | baixar, interpretar regras e validar permissões |
| Busca pelo assunto | **Selenium** (Chrome headless) | abrir o site, acionar o menu de skills e clicar em "Python" |
| Navegação pelas páginas | `requests` + BeautifulSoup | baixar cada página de resultados e achar o link "Next" |
| Extração dos campos | BeautifulSoup (seletores CSS) + `re` | localizar título, empresa, local, salário, requisitos |
| Limpeza e deduplicação | `pandas` | `drop_duplicates`, `fillna`, contagem de campos ausentes |
| Gravação | `pandas` / `csv` / `json` | gerar `.csv` (UTF-8 com BOM) e `.json` |

A **busca é feita pelo código**, não por URL digitada à mão: o Selenium abre `/jobs`, clica no elemento "Todos os skills" para abrir o modal e clica no link cujo texto é exatamente `Python`, deixando que o próprio site conduza à página de resultados (`driver.current_url`). Se o Selenium não estiver instalado ou o layout mudar, há um *fallback* que navega diretamente para a URL de resultados — o programa registra o desvio no log e continua, em vez de quebrar.

## 4. Métodos de busca utilizados no código

| # | Método | O que localiza exatamente |
|---|---|---|
| 1 | XPath `//*[contains(normalize-space(text()),'Todos os skills')]` | o botão/rótulo que abre o modal com a lista completa de tecnologias |
| 2 | XPath `//a[normalize-space(text())='Python']` | dentro do modal, a âncora cujo texto é exatamente o termo buscado (evita casar com "PyTorch", "Pyramid") |
| 3 | CSS `a[href*='/jobs/']` | todas as âncoras cujo `href` contém `/jobs/` — candidatas a link de vaga na listagem |
| 4 | Regex `^/jobs/\d+-[^/?#]+$` | filtra o item 3, mantendo só as URLs canônicas de vaga (`/jobs/33771-junior-fullstack-developer`) e descartando filtros (`/jobs?contract_type=PJ`), páginas (`/jobs/page/2`) e links de skill (`/jobs-python`) |
| 5 | CSS `a[href]` + regex `[?&]page=(\d+)` no `href` **e** teste de texto (`next`, `›`, `próxima`) | o link de paginação para a página seguinte, lido do próprio HTML |
| 6 | Regex `[?&]page=(\d+)` | remove o parâmetro de página da URL para remontar o endereço da próxima página quando o link "Next" não existe |
| 7 | CSS `h1` | o título da vaga na página de detalhe |
| 8 | CSS `a[href*='/companies/']` + regex `/companies/\d+` | o nome da empresa (link para o perfil corporativo, com id numérico — exclui `/companies/sign_in`) |
| 9 | Regex `Localiza[cç][aã]o:\s*([^\n]+)` | o texto que segue o rótulo "Localização:" (cidade/modalidade) |
| 10 | Regex `Sal[aá]rio:\s*([^\n]+)` | a faixa salarial declarada ("Até R$3.000", "Acima de R$18.000") |
| 11 | Regex `R\$\s?\d{1,3}(?:\.\d{3})+(?:,\d{2})?` | valores monetários soltos no corpo do anúncio — usada só quando o rótulo "Salário:" traz "Não especificado". O `+` no grupo de milhar é deliberado: exigindo o separador, trechos como "R$ 50 milhões" da descrição institucional deixam de ser lidos como salário |
| 12 | Regex `\b(CLT\|PJ\|Est[aá]gio\|Freelancer)\b` | o tipo de contrato |
| 13 | Regex `\b(J[uú]nior\|Pleno\|S[eê]nior\|Est[aá]gio\|Trainee)\b` (com `IGNORECASE`) | o nível de senioridade (procurado primeiro no título, depois no corpo) |
| 14 | CSS `a[href^='/jobs-']` + exclusões | as tags de tecnologia da vaga; exclui `/jobs-city/...` (localidade) e os links do rodapé, que começam com "Vagas programador…" |
| 15 | `find_all(['h2','h3','h4','h5'])` + regex no texto do cabeçalho | os títulos das seções "Requisitos", "Atividades e Responsabilidades" e "Descrição da empresa"; o conteúdo é montado percorrendo os irmãos seguintes até o próximo cabeçalho |
| 16 | Regex `^\s*Disallow:\s*(\S*)` e `^\s*Sitemap:\s*(\S+)` (multiline) | as regras de bloqueio e as declarações de sitemap dentro do `robots.txt` |
| 17 | Regex `<loc>\s*(.*?)\s*</loc>` | cada URL listada no arquivo XML do sitemap |
| 18 | Regex `\s+` | normalização de espaços, tabulações e quebras de linha em todos os campos textuais |

**Uma armadilha da paginação.** O método 5 começou testando apenas o *texto* da âncora. O problema é que o card de qualquer vaga que use a tecnologia **NextJS** contém a palavra "next" e, estando antes do rodapé no HTML, era aceito como se fosse o botão de próxima página. O efeito foi silencioso e grave: a "terceira página" coletada era, na verdade, a página de detalhe de uma vaga, de onde o script extraiu links de *vagas relacionadas* — duas delas sem qualquer relação com Python. A correção foi exigir as duas condições simultaneamente: o texto indicar avanço **e** o `href` ser de fato um link de paginação (`?page=N`). Como rede de segurança, `coletar_links()` ainda verifica se a URL obtida casa com o padrão de página de vaga e interrompe a varredura se casar, em vez de coletar dados errados.

## 5. Tratamento dos dados

**Duplicatas.** Atuam três barreiras: um `set` de URLs já vistas durante a varredura das páginas (a mesma vaga costuma reaparecer entre páginas quando a ordenação muda entre uma requisição e outra); `drop_duplicates(subset=['link'])`; e `drop_duplicates(subset=['titulo','empresa'])`, que remove republicações do mesmo anúncio com IDs diferentes — situação observada no portal, onde uma vaga chega a aparecer duas vezes na mesma página com URLs distintas.

**Campos ausentes.** Toda extração passa pela função `limpar()`, que devolve `"Nao informado"` quando o valor é `None` ou string vazia, normaliza espaços e trunca textos longos (requisitos e descrição são limitados a 3.000 caracteres, cortando na última palavra inteira).

Há, porém, um caso que `limpar()` sozinha não resolve e que é o mais frequente neste portal: o campo **não** vem vazio — vem preenchido com um rótulo que significa "ausente". O ProgramaThor escreve literalmente `Salário: Não especificado`. Como essa é uma string não vazia, ela era capturada como se fosse uma faixa salarial válida; a consequência é que o *fallback* para valores em R$ nunca era acionado e a estatística de campos ausentes acusava **zero** vagas sem salário, quando na verdade eram quase 70% delas. Introduziu-se por isso a função `limpar_opcional()`, que compara o valor já normalizado com um conjunto de rótulos de ausência (`SEM_INFORMACAO`: "Não especificado", "A combinar", "-"…) e o converte em `"Nao informado"`. Só então a cascata do salário funciona como descrito: rótulo "Salário:" → valor em R$ no corpo do anúncio → `"Nao informado"`.

**Normalização do nível.** O regex do método 13 usa `IGNORECASE` e devolve o texto exatamente como aparece na página, o que produzia `Sênior`, `Senior` e `PLENO` como categorias distintas — inúteis como chave de agrupamento. A função `normalizar_nivel()` remove acentos, aplica minúsculas e mapeia o resultado para uma forma canônica (`Junior`, `Pleno`, `Senior`, `Trainee`, `Estagio`).

Quando nenhuma seção nomeada é reconhecida na página, a descrição recebe o texto útil da página como último recurso, de modo que a coluna nunca fica vazia.

**Exceções.** `baixar_pagina()` encapsula todos os erros de rede (`requests.exceptions.RequestException`), respeita o `timeout`, repete até 3 vezes com espera progressiva e devolve `None` em vez de propagar a falha. O laço principal simplesmente pula a vaga cujo download falhou. `extrair_vaga()` envolve todo o *parsing* em `try/except`, registrando o erro no log e seguindo adiante. A rotina do Selenium tem `try/except/finally`, garantindo `driver.quit()` mesmo em caso de erro, e cai no modo sem navegador se algo der errado. O resultado é que uma página malformada ou fora do ar não interrompe a coleta.

## 6. Resultados e limitações

Foram percorridas **3 páginas de resultados** — `/jobs-python`, `?page=2` e `?page=3` —, gerando um arquivo final com as colunas: `titulo`, `empresa`, `local`, `faixa_salarial`, `tipo_contrato`, `nivel`, `tecnologias`, `requisitos`, `descricao`, `link`, `pagina_origem`, `data_coleta`.

Números da execução final:

| Indicador | Valor |
|---|---|
| Regras `Disallow` lidas no `robots.txt` | 4 (`/admin/`, `/user/`, `/users/`, `/company/`) |
| URLs listadas no sitemap | 30.382 (30.364 contendo `/jobs`) |
| `can_fetch('/jobs')` | `True` |
| Links de vaga únicos coletados nas 3 páginas | 44 (15 + 15 + 14) |
| Páginas de vaga que retornaram HTTP 500 no portal | 2 (puladas sem interromper a coleta) |
| Registros extraídos | 42 |
| Registros após deduplicação | 42 (nenhuma duplicata nesta execução) |
| Empresas distintas | 29 |
| Vagas **sem** faixa salarial divulgada | 29 de 42 (69%) |
| Vagas sem empresa identificada | 5 de 42 (anúncios sem perfil corporativo vinculado) |
| Distribuição por nível | Senior 20 · Pleno 19 · Junior 3 |
| Distribuição por contrato | PJ 26 · CLT 16 |

As 42 vagas têm Python entre as tecnologias, o que confirma que a busca da Etapa 2 e a paginação da Etapa 3 permaneceram dentro do recorte pretendido. A deduplicação não removeu nada nesta execução; sua utilidade ficou demonstrada numa execução anterior, em que o portal exibia o mesmo anúncio sob dois IDs (`/jobs/33756-…` e `/jobs/33760-engenheiro-de-automacao-ia-senior`).

A principal limitação é a dependência da estrutura do HTML: mudanças de layout do portal exigem revisão dos seletores. Por isso optou-se, sempre que possível, por âncoras estáveis — padrão de URL, rótulos de texto ("Salário:", "Requisitos") e tags semânticas (`h1`) — em vez de nomes de classe CSS, que costumam ser gerados automaticamente e mudam com frequência. Outra limitação é que a faixa salarial, quando ausente no anúncio, não pode ser inferida: com 29 das 42 vagas sem esse dado, qualquer análise estatística sobre remuneração se apoia em apenas 13 observações. Por fim, o campo `tipo_contrato` é obtido pela primeira ocorrência de "CLT"/"PJ" no texto da página; embora o portal exiba esse dado num bloco fixo logo abaixo do nome da empresa — o que torna a primeira ocorrência confiável na prática —, trata-se de uma âncora posicional, não semântica, e portanto mais frágil que as demais.
