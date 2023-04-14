import openai
import spacy
import ffmpeg
import tempfile
import os
import streamlit as st
from io import BytesIO

st.set_page_config(
    page_title="オート議事録",
    page_icon='comment_edit.ico',
    layout="wide",
    initial_sidebar_state="auto",
)

# APIキー
openai.api_key = st.secrets["apikey"]

# 分割秒数
split_time = 5 * 60

# whisper調整用プロンプト
whisperprompt = 'こんにちは。今日はいいお天気ですね。私はWeb広告の代理店、ウェブ広告代理店のゲンダイエージェンシー株式会社の者です。GDNやYDAなどの運用、別途費用が発生しますが、ランディングページの作成をします。御社の取り組みも知りたいです。代理店契約。'

# プロンプトテンプレート
template1 = """
# instruction
    You are an expert writer that speaks and writes fluent japanese.
    You will receive a transcription of a part of the audio of the business-to-business meeting.
    Briefly summarize the contents what was discussed of the given meeting audio in 日本語.

# constraints
    - Please respond only in the japanese language.
    - Do not self reference.
    - Do not explain what you are doing.
    - Do not miss important keywords.
    - Do not change the meaning of the sentence.
    - Do not use fictitious expressions or words.
    - Since it is known that this is a business meeting, there is no need to include it in the summary.
"""

# 出力先変数初期化
text = ''
summary = ''

# 入力ファイル
input = st.sidebar.file_uploader("動画ファイルをアップロードしてください")

# コンテンツ表示用コンテナ初期化
block = st.container()

# 入力ファイルが入った場合
if input is not None:

    # ファイルの表示
    block.video(input)
    file_bytes = input.read()
    file_bytesio = BytesIO(file_bytes)

    # 一時ファイルに保存する
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(file_bytes)
        input_path = f.name

    # メディア情報取得
    probe = ffmpeg.probe(input_path)
    info = next(s for s in probe['streams'] if s['codec_type'] == 'video')

    # 尺
    duration = float(info['duration'])

    # メッセージプレースホルダ
    placeholder = block.empty()

    # 尺が5分以下の場合
    if duration <= split_time:
        placeholder.info('文字起こし処理中...')
        bar = block.progress(0)
        # 出力音声ファイル名
        output_file = f'audio.mp3'

        # エンコード処理
        stream = ffmpeg.input(input_path)
        audio = stream.audio
        audio = ffmpeg.output(audio, output_file, acodec='libmp3lame')
        process = ffmpeg.run(audio, overwrite_output=True)
        bar.progress(50)

        # 文字起こし処理（Whisper）
        audio_file = open(output_file, "rb")
        transcript = openai.Audio.transcribe(
            "whisper-1", audio_file, prompt=whisperprompt)

        text = transcript.text
        summary = text
        bar.progress(100)

    # 尺が5分超えの場合
    else:
        # 分割処理
        placeholder.info('分割・文字起こし処理中...')
        bar = block.progress(0)
        for t in range(0, int(duration), split_time):

            bar.progress(int(((int(t/split_time)+1)/(int(duration/split_time)+1))*100)-5)

            # 出力音声ファイル名
            output_file = f'audio_{t}.mp3'

            # 分割・エンコード処理
            stream = ffmpeg.input(input_path, ss=t, t=split_time)
            audio = stream.audio
            audio = ffmpeg.output(audio, output_file, acodec='libmp3lame')
            process = ffmpeg.run(audio, overwrite_output=True)
            bar.progress(int(((int(t/split_time)+1)/(int(duration/split_time)+1))*100)-2)

            # 文字起こし処理（Whisper）
            audio_file = open(output_file, "rb")
            transcript = openai.Audio.transcribe("whisper-1", audio_file, prompt=whisperprompt, temperature=0.1)

            text += transcript.text

            # 一次要約処理（GPT）
            completion = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                temperature=0.1,
                messages=[
                    {
                        "role": "system",
                        "content": template1
                    },
                    {
                        "role": "user",
                        "content": transcript.text
                    }
                ]
            )

            # 要約結果
            response_text = completion.choices[0].message.content
            summary += response_text
            bar.progress(int(((int(t/split_time)+1)/(int(duration/split_time)+1))*100))

        placeholder.success('分割・文字起こし完了')

    nlp = spacy.load('ja_ginza')
    doc = nlp(text)

    pritty = ''
    for sent in doc.sents:
        pritty += f'{sent.text}\n'

    expander1 = block.expander("中間出力")
    expander1.write(pritty)

    placeholder.info('要約中...')
    bar.progress(0)

    # 本要約

    # プロンプトテンプレート
    template2 = """
    # instruction
        You are an expert writer that speaks and writes fluent japanese.
        You will receive a summary statement of the business-to-business meeting.
        Please make a further summary in Markdown format based on all the given text in 日本語.

    # constraints
        summarize the Summary in the following format.

        ----------------------------------------------
        ## 課題点
            #### h4 headings（複数可）
                - コンテンツ（複数可）
        ## 求めること
            #### h4 headings（複数可）
                - コンテンツ（複数可）
        ## 提案内容
            #### h4 headings（複数可）
                - コンテンツ（複数可）
        ## ネクストアクション
            #### h4 headings（複数可）
                - コンテンツ（複数可）
        ## その他
            #### h4 headings（複数可）
                - コンテンツ（複数可）
        ----------------------------------------------

        - You are an expert writer that speaks and writes fluent japanese.
        - Please respond only in the japanese language.
        - Do not self reference.
        - Do not explain what you are doing.
        - use h4 headings and list to make the hierarchical structure.
        - Please describe each item in detail.
        - Avoid writing the same thing over and over again that means the same thing.
        - Do not miss important keywords.
        - Do not change the meaning of the sentence.
        - Do not use fictitious expressions or words.
        - Since it is known that this is a business meeting, there is no need to include it in the summary.
    """

    bar.progress(50)

    # 要約処理（GPT）
    completion = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        temperature=0.1,
        messages=[
            {
                "role": "system",
                "content": template2
            },
            {
                "role": "user",
                "content": summary
            }
        ]
    )

    # 要約結果
    response_text = completion.choices[0].message.content

    bar.progress(100)
    placeholder.success('要約完了')
    # マークダウン出力
    expander2 = block.expander("要約")
    expander2.markdown(response_text)

    # 一時ファイルを削除する
    os.remove(input_path)
