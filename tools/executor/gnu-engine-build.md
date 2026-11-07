# Construction du contrôleur GNU ARM64 séparé

Le contrôleur qui héberge le moteur et l'interface officielle reste dans le
userspace GNU/PRoot existant. Sa cible est donc `aarch64-unknown-linux-gnu`.
Ce binaire **n'est pas Bionic**. Les outils du modèle doivent être lancés par
le backend Bionic distinct. Aucun de ces scripts n'utilise ADB ou le téléphone.

## 2026-11-06：升级至 Codex 0.167.0

当前构建器绑定官方 `rust-v0.167.0`，提交
`086ccc833bc9cf01024ad2dd6af7dbd421b6bf9a`。手机原生执行、共享目录配置
和设备桥保持现有边界；配套桌面前端升级至 Linux ARM64 `26.1103.31037`。
当前实机验证范围见 [兼容性与验证](../../docs/compatibility.md)。

本次源码为 `$HOME/src/codex-native-0.167.0`，发布缓存为
`$HOME/engine-gnu-target-0167`，实际构建状态指针位于
`work/upgrade-20261106/engine-state.txt`。按用户当前要求保留 Cargo target、
registry/git、Gradle 和 Android 编译缓存，不执行历史清理脚本。
后续构建可继续显式选择本次 target 目录复用缓存。

下面 0.165.0 的具体路径与检查结果为历史记录，不能用作 0.167.0 的验收。

## 2026-10-28：升级至 Codex 0.165.0

2026-10-28 的构建器使用官方 `rust-v0.165.0`，提交
`360319d8dee62d87e2d59fc0c21805d79519cfed`，工具链为 Rust 1.99.1。
Android 原生执行器保持独立；GNU 控制器和匹配的 Code Mode host 必须一起更新。
下面的历史验证记录仍属于各自注明的旧版本，不能作为新版手机验证结果。

默认构建仍从恢复补丁重建独立快照。迁移期间可在 `prepare` 命令上加
`--verified-checkout --engine $HOME/src/codex-native-0.165.0`，
复用已有 Cargo 编译路径：构建器先重建正式快照，再逐文件比较工作树的
内容、权限和链接。只排除工作树根目录的 `.git` 管理指针；未记录文件、
忽略文件或错误的上游提交都会使准备失败。构建前后仍检查源码没有变化，
并保留正式快照，不能用一次失败构建生成已完成的发布记录。

成功执行 `build` 和 `package` 后，运行：

```sh
python3 -B tools/executor/stage-gnu-engine-assets.py \
  --state downloads/engine-gnu-arm64/20261028T035038Z-094a5a9bc738/build-state.json \
  --output $HOME/engine-apk-assets-0.165.0-20261028
```

这里的状态文件必须是该次构建真实生成的文件。Android 构建通过
`-PcodexGnuEngineAssets=$HOME/engine-apk-assets-0.165.0-20261028`
包含这对执行文件。
安装器在启动前完整暂存两份文件，再替换程序并写入版本收据；首次更新
校验载荷，后续启动通过收据和文件身份判断是否需要更新。

安装及手机验证成功后，可清理该次 Cargo target 和依赖下载缓存。
保留源码恢复补丁、最终 APK、发布包以及必要的回滚文件。若使用临时
本机 Cargo 下载代理，停止代理前应撤销相应 source replacement，
避免下一次构建指向已停止的服务。WSL 内删除缓存不会自动压缩 Windows
上的虚拟磁盘文件，应分别报告 Linux 可用空间和 Windows 实际变化。

## Preuves disponibles le 8 septembre 2026

- Base moteur : `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a`, Rust 1.95.0.
- La construction GNU ARM64 du 7 septembre a effectivement terminé en 18 min 08 s.
  Ses binaires correspondent à l'ancien patch `3de9c0db…`, pas au patch courant.
  Elle ne dispense donc pas de construire les corrections exportées aujourd'hui.
- Les outils GCC/G++ ARM64, binutils, CMake et Ninja étaient présents lors de
  l'inventaire PC. La prévalidation ci-dessous les relit avant chaque préparation.
- V8 doit conserver la paire officielle `ptrcomp_sandbox_release`, version
  résolue par le `Cargo.lock`. `scripts/codex_package/v8.py` du moteur vérifie
  l'archive et les bindings ensemble contre le manifeste SHA officiel.
- Le préfixe OpenSSL 3.6.3 de ce poste historique avait ses deux archives
  statiques qualifiées. Ces entrées et leur ancien `SHA256SUMS` ne font pas
  partie du dépôt public. Un nouveau poste doit fournir son propre manifeste
  explicite, selon la procédure ci-dessous ; les anciennes empreintes ne sont
  ni inventées ni remplacées par une acceptation automatique des fichiers.
- Le vérificateur ELF ajouté a été exécuté le 8 septembre sur les deux vrais
  binaires historiques et les cinq bibliothèques réellement collectées du Fold.
  Tous les imports forts, noms et versions, sont résolus dans leur fermeture
  de dépendances. Aucun binaire ARM64 n'a été exécuté pour ce contrôle.
- La libc collectée provient du Debian du Fold, pas de Bionic. Les anciens
  binaires demandent au maximum `GLIBC_2.39`; la libc collectée exporte
  `GLIBC_2.41`, relu avec LLVM readelf le 8 septembre. Le nouveau contrôle devra être
  réexécuté sur les nouveaux binaires. Un passage sur les anciens ne les valide
  pas. Les bibliothèques du téléphone devront être recollectées si le rootfs
  a changé depuis cette collecte.

Rapport courant du contrôle statique :
`work/root-artifacts-20260907/arm-engine-script-static-compatibility-20260908.json`.
Les absences d'imports faibles sont listées séparément dans ce rapport.

## Commandes reproductibles

Le stockage de compilation est une exception locale prévue au dossier Windows
du projet : sources figées et sorties Cargo restent sur le disque Linux de WSL.
Le dépôt, les exports de récupération et les preuves livrables restent dans
`C:\Dev\Codex`. À l'installation du poste, créer le sous-dossier dédié
au compte de compilation, sans changer le propriétaire du préfixe `/opt` :

```sh
sudo install -d -o codex-build -g codex-build -m 0755 /opt/codex/engine-gnu-arm64/builds
```

Depuis WSL Ubuntu-24.04, utilisateur `codex-build`, après l'export moteur
canonique et lorsque les sources à livrer sont arrêtées :

```sh
cd /mnt/c/Dev/Codex
python3 -B tools/executor/build-gnu-engine.py prepare \
  --dependency-manifest /opt/codex/engine-gnu-arm64/dependency-inputs.json
```

`prepare` ne compile pas Rust. Il crée un dossier neuf sous
`/opt/codex/engine-gnu-arm64/builds`, reconstitue `git archive BASE` plus le patch
exporté, vérifie les dépendances et conserve les sources/empreintes/outils sous
`downloads/engine-gnu-arm64/<date>-<patch>/`. Il imprime le chemin exact du
`build-state.json`. Le worktree et son index ne sont jamais modifiés. Aucun
script n'utilise les anciens emplacements Windows hors du dossier projet.

## Entrées OpenSSL explicites sur un nouveau poste

Le préfixe attendu est `--dependencies/openssl`, avec `lib/libssl.a`,
`lib/libcrypto.a` et `include/openssl/`. Il s'agit de bibliothèques **GNU/Linux
ARM64**, compilées avec `aarch64-linux-gnu-gcc`, pas de bibliothèques Android
NDK/Bionic ni de bibliothèques x86_64 du poste. Aucun de ces fichiers n'est
téléchargé ou construit par `prepare`.

La recette existante dans `tools/ci/native_validation.py::arm_dependencies`
utilise OpenSSL 3.6.3 officiel :

- Source : `https://github.com/openssl/openssl/releases/download/openssl-3.6.3/openssl-3.6.3.tar.gz`.
- SHA256 du tar source : `243a86649cf6f23eeb6a2ff2456e09e5d77dd9018a54d3d96b0c6bdd6ba6c7f1`.
- Configuration : `perl ./Configure linux-aarch64 --cross-compile-prefix=aarch64-linux-gnu- no-shared --libdir=lib --prefix=/opt/codex/engine-gnu-arm64/deps/openssl --openssldir=/usr/lib/ssl`.
- Construction et installation : `make -j2 build_sw`, puis `make install_sw`.

Vérifier le tar contre ce SHA **avant de l'extraire ou d'exécuter Configure**.
Conserver le tar ainsi que les commandes, versions du compilateur, journaux de
configuration/construction/installation et leurs codes de sortie. Utiliser un
dossier de sources neuf sur le disque Linux. `--libdir=lib` rend explicite le
chemin requis par le builder. Le stage CI prépare aussi d'autres répertoires
et exige `GITHUB_ENV` ; il ne faut pas le lancer comme une commande autonome de
provisionnement local.

Après une construction réussie et revue, créer le manifeste suivant à partir
des **vrais fichiers**, en choisissant un chemin de sortie neuf. Ce sont de
nouvelles empreintes qualifiées pour ce préfixe, pas celles du poste historique :

```sh
python3 - /chemin/conserve/openssl-3.6.3.tar.gz \
  /opt/codex/engine-gnu-arm64/deps/openssl \
  /opt/codex/engine-gnu-arm64/dependency-inputs.json <<'PY'
import hashlib, json, pathlib, sys
source, prefix, output = map(pathlib.Path, sys.argv[1:])
def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
value = {
    'schema': 'codex.gnu-engine-dependencies.v1',
    'target': 'aarch64-unknown-linux-gnu',
    'openssl': {
        'version': '3.6.3',
        'source': {
            'url': 'https://github.com/openssl/openssl/releases/download/openssl-3.6.3/openssl-3.6.3.tar.gz',
            'archive': str(source.resolve()),
            'sha256': sha(source),
        },
        'configureTarget': 'linux-aarch64',
        'compilerTarget': 'aarch64-linux-gnu',
        'archives': {name: sha(prefix / 'lib' / name)
                     for name in ('libssl.a', 'libcrypto.a')},
    },
}
with output.open('x', encoding='utf-8') as stream:
    json.dump(value, stream, indent=2)
    stream.write('\n')
PY
```

Le champ `source.archive` accepte aussi un chemin relatif au manifeste.
`--cargo-home` et `--rustup-home` sélectionnent les installations Rust locales
et sont conservés dans l'état de construction. Par défaut, les variables
`CARGO_HOME` / `RUSTUP_HOME` ou les emplacements standards du compte courant
sont utilisés ; aucun répertoire privé `/opt/codex` n'est ajouté au `PATH`.
`prepare` exige le manifeste, vérifie l'identité source verrouillée et le vrai
tar, les deux SHA de bibliothèques, la version des headers et tous les membres
ELF64/AArch64 little-endian de type `REL`. Les archives minces (`!<thin>`) sont
refusées car leurs objets externes ne sont pas couverts par leur SHA. Les
liens symboliques du préfixe ne peuvent pas sortir de ce préfixe. Ces contrôles
ont lieu avant tout téléchargement de V8, puis à nouveau après celui-ci.
Un SHA de bibliothèque incorrect, un tar absent ou une architecture incorrecte
arrête la préparation ; aucune empreinte de bibliothèque n'est régénérée par
le builder.

La provenance de construction déclarée dans le manifeste reste liée à la
revue de la recette et des journaux : un hash de tar n'est pas une attestation
cryptographique que le compilateur a utilisé ce tar. Le contrôle ELF distingue
les architectures ; l'origine GNU/Bionic repose aussi sur la recette et le
compilateur conservés. Les hashes réels de tout le préfixe et les fichiers
`DEPENDENCY-INPUTS.json` / `DEPENDENCY-CHECKS.json` sont figés avec les preuves,
revérifiés lors de `build` et `package`, puis inclus dans le paquet.

Tests hors réseau du refus des entrées invalides et de l'analyse des en-têtes
readelf (ils ne compilent ni OpenSSL ni Rust et n'exécutent pas d'ARM64) :

```sh
python3 -B -m unittest discover -s tests -p 'test_gnu_engine_dependencies.py' -v
```

Le builder vérifie le montage réel avec `findmnt`, après résolution des liens,
avant de préparer les sources puis avant de compiler. Il refuse les répertoires
de sources/cache sur les montages Windows ou partagés, même avec une option
`--build-root` ou `--target-dir` explicite. Il vérifie aussi les droits d'écriture
du compte et enregistre le système de fichiers dans `build-state.json`.
Ne pas déplacer les sources d'une compilation en cours : préparer un nouvel
état sur Linux après sa fin ou son interruption, en conservant le cache Cargo.

Régression sur les vrais montages WSL, avec un dossier temporaire Linux :

```sh
TMPDIR=/opt/codex/engine-gnu-arm64/builds python3 -B -m unittest discover -s tests -p 'test_gnu_engine_storage.py' -v
```

Puis, avec le chemin exact imprimé :

```sh
python3 -B tools/executor/build-gnu-engine.py build --state /chemin/imprime/build-state.json
python3 -B tools/executor/build-gnu-engine.py package --state /chemin/imprime/build-state.json
```

Le nombre de jobs reste le défaut Cargo, sauf `--jobs N` choisi selon les
ressources disponibles. Ne pas lancer un build ARM64 concurrent aux tests
globaux Rust ou aux tests de workers utilisant le même budget de processus.

La commande réelle est `cargo build --locked --target aarch64-unknown-linux-gnu
--release --timings -p codex-cli --bin codex -p codex-code-mode-host --bin
codex-code-mode-host`. Elle conserve le point d'entrée `codex app-server` et le
compagnon `codex-code-mode-host` adjacent, conformément à `install-context`.
Chaque tentative possède son propre journal et code de sortie. Après succès,
les binaires sont figés avant une éventuelle réutilisation du cache Cargo.

Le paquet contient les deux exécutables, leurs identités et la provenance des
sources. Les symboles de débogage disposent d'une archive séparée. Les deux
archives ont un manifeste SHA256, un ordre et des métadonnées déterministes.
La compilation elle-même n'est pas déclarée reproductible octet par octet.
Ce paquet est un payload de notre moteur, pas un remplacement du paquet
officiel ou de ses ressources.

## Ce qui manque encore pour le lancement réel

Le code de production `cli/src/main.rs` et `app-server/src/main.rs` n'injecte
pas encore `ExecServerLocalRuntime`. La preuve app-server v9 construit ce
runtime dans sa fixture de test. Pointer simplement `CODEX_CLI_PATH` vers la
CLI construite ne raccorde donc pas le backend natif et ne corrige pas le
problème de lancement à lui seul.

Le lanceur de production doit accepter les argv réels du client, authentifier
le transport une seule fois, construire le vrai runtime avec ses fichiers de
configuration et appeler l'app-server. Il doit préserver stdio, les arguments,
les annulations et les erreurs de lancement. Il ne doit jamais retomber sur
l'exécuteur Linux si l'initialisation native échoue. Les fixtures SSE et les
options qui désactivent des tâches de démarrage pour les tests ne sont pas un
lanceur à déployer.

Le raccordement de chemins est décrit dans
`work/root-artifacts-20260907/shared-paths-final-connection-plan.md`. Il garde
le HOME et le profil GNU du contrôleur et publie les vrais chemins du projet
et de l'IPC. Le backend Bionic doit construire son propre environnement ; les
variables de bibliothèques du contrôleur ne sont pas compatibles avec lui.

Le `CODEX_CLI_PATH` de production, le bootstrap authentifié, le partage mesuré
et le test réel depuis l'interface restent à livrer. Aucun paquet produit par
ces scripts ne doit être déclaré qualifié Android avant ces vérifications.
