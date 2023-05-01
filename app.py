import openai
import spacy
import ffmpeg
import tempfile
import os
import streamlit as st
from io import BytesIO
import uuid
import pymysql.cursors

st.set_page_config(
    page_title="オート議事録",
    page_icon='comment_edit.ico',
    layout="wide",
    initial_sidebar_state="auto",
)

conn = pymysql.connect(
    host=st.secrets["host"],
    user=st.secrets["user"],
    password=st.secrets["password"],
    database=st.secrets["database"],
    cursorclass=pymysql.cursors.DictCursor
)

# APIキー
openai.api_key = st.secrets["apikey"]

# 分割秒数
split_time = 10 * 60

# whisper調整用プロンプト
whisperprompt = 'こんにちは。今日はいいお天気ですね。私はWeb広告の代理店、ウェブ広告代理店のゲンダイエージェンシー株式会社の者です。GDNやYDAなどの運用、別途費用が発生しますが、ランディングページの作成などもします。御社の取り組みも知りたいです。代理店契約しますか？'

# プロンプトテンプレート
template1 = """
# instruction
    You are an expert writer that speaks and writes fluent japanese.
    You have a Descriptive writing style.
    You will receive a transcription of a part of the audio of the business meeting.
    Briefly summarize the contents what was discussed of the given meeting audio in 日本語.

# constraints
    - Please list only a summary.
    - Please respond only in the japanese language.
    - Please do not self reference.
    - Please do not explain what you are doing.
    - Please not miss important keywords.
    - Please do not change the meaning of the sentence.
    - Please do not use fictitious expressions or words.
    - Please do not preface your summary like "At the meeting -".
"""

# 出力先変数初期化
text = ''
text_withtime = ''
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

    # 尺が12分以下の場合
    if duration <= split_time:
        placeholder.info('処理中...')
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
        transcript = openai.Audio.transcribe("whisper-1", audio_file, language="ja", prompt=whisperprompt,
                                             temperature=0, response_format="verbose_json")

        for segment in transcript.segments:
            start_m, start_s = divmod(int(segment.start), 60)
            start_h, start_m = divmod(start_m, 60)
            start = f"{start_h:02d}:{start_m:02d}:{start_s:02d}"

            end_m, end_s = divmod(int(segment.end), 60)
            end_h, end_m = divmod(end_m, 60)
            end = f"{end_h:02d}:{end_m:02d}:{end_s:02d}"

            text_withtime += f'[{start} - {end}]: {segment.text.encode().decode("utf-8")}\n'

        # 要約処理（GPT）
        completion = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            temperature=0,
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
        summary = completion.choices[0].message.content
        bar.progress(100)

    # 尺が5分超えの場合
    else:
        # 分割処理
        placeholder.info('処理中...')
        bar = block.progress(0)
        offset = 0.00
        for t in range(0, int(duration), split_time):

            bar.progress(int(((int(t/split_time)+1)/(int(duration/split_time)+1))*100)-4)

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
            transcript = openai.Audio.transcribe("whisper-1", audio_file, language="ja", prompt=whisperprompt,
                                                 temperature=0, response_format="verbose_json")
            for segment in transcript.segments:
                start_m, start_s = divmod(int(offset + segment.start), 60)
                start_h, start_m = divmod(start_m, 60)
                start = f"{start_h:02d}:{start_m:02d}:{start_s:02d}"

                end_m, end_s = divmod(int(offset + segment.end), 60)
                end_h, end_m = divmod(end_m, 60)
                end = f"{end_h:02d}:{end_m:02d}:{end_s:02d}"

                text_withtime += f'[{start} - {end}]: {segment.text.encode().decode("utf-8")}\n'
            offset += segment.end

            text += transcript.text

            # 要約処理（GPT）
            completion = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                temperature=0,
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
            summary += completion.choices[0].message.content
            bar.progress(int(((int(t/split_time)+1)/(int(duration/split_time)+1))*100))

    # 文字起こし出力
    expander1 = block.expander("文字起こし")
    expander1.text(text_withtime)

    # 要約出力
    expander2 = block.expander("要約")
    nlp = spacy.load('ja_ginza')
    doc = nlp(summary)
    for sent in doc.sents:
        expander2.write(f' - {sent.text}')

    with conn:
        with conn.cursor() as cursor:
            # レコードを挿入
            sql = "INSERT INTO `summary` (`id`, `title`, `transcript`, `summary`, `comment`) VALUES (%s, %s)"
            cursor.execute(sql, (uuid.uuid4().hex, 'hongehonge',text_withtime,summary,'none'))

        # コミットしてトランザクション実行
        conn.commit()

    # 一時ファイルを削除する
    os.remove(input_path)
    placeholder.success('処理完了')
