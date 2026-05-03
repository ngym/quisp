# diagrams.net ライブラリとしての QuISP アイコン

> **English version**: see [README.md](README.md).

[diagrams.net](https://app.diagrams.net/)（旧 draw.io）は無料のオンライン作図ソフトです。

このリポジトリ内のすべての SVG アイコンを束ねた diagrams.net ライブラリとして開けるファイルが `quisp.xml` です（File -> Open Library...）。

ライブラリを開くと、アプリケーションに同梱の既定形状と同じように、図中で使える _shape_ の集合として現れます。

ワークスペースにライブラリを取り込んだ後は、各円形アイコンの "perimeter" 既定スタイルを "ellipse" に設定することを推奨します。
こうすると接続線がアイコンの境界（不可視の正方形ではなく）に触れるようになります。
この設定はワークスペースに `quisp.xml` を取り込むたびに必要ですが、ローカル版またはサインイン版を使っている場合は保存されます。

![](screenshot.png)
