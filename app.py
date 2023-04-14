import openai
import ffmpeg
import tempfile
import os
import streamlit as st
from io import BytesIO

# APIキー
openai.api_key = st.secrets["apikey"]

# 音声チャンクの保存先
output_dir = './audio/'

# 分割秒数
split_time = 5 * 60

# プロンプトテンプレート
template = """
You will receive a transcription of a portion of the audio of the business-to-business meeting.

Briefly summarize the contents what was discussed of the given business meeting audio in 日本語.

Since it is known that this is a business meeting, there is no need to include it in the summary.
"""

# 出力先変数初期化
text = ''
summary = ''

# 入力ファイル
input = st.file_uploader("動画ファイルをアップロードしてください")

# 入力ファイルが入った場合
if input is not None:

   # ファイルの表示
   st.video(input)
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

   # 分割処理
   st.write('分割処理中...')
   bar = st.progress(0)
   for t in range(0, int(duration), split_time):

      bar.progress(int(((int(t/split_time)+1)/(int(duration/split_time)+1))*100))

      # 出力音声ファイル名
      output_file = f'{output_dir}/audio_{t}.mp3'

      # 分割・エンコード処理
      stream = ffmpeg.input(input_path, ss=t, t=split_time)
      audio = stream.audio
      audio = ffmpeg.output(audio, output_file, acodec='libmp3lame')
      process = ffmpeg.run(audio, overwrite_output=True)

      # 文字起こし処理（Whisper）
      audio_file = open(output_file, "rb")
      transcript = openai.Audio.transcribe(
         "whisper-1", audio_file, prompt="こんにちは。今日は、いいお天気ですね。私は、Web広告の代理店、いわゆるWeb広告代理店の者です。GDNやYDAなどの運用や、ランディングページの作成をします。御社の取り組みも知りたいです。")

      text += transcript.text

      # 一次要約処理（GPT）
      completion = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[
         {
               "role": "system",
               "content": template
         },
         {
               "role": "user",
               "content": transcript.text
         }
      ])

      # 要約結果
      response_text = completion.choices[0].message.content
      summary += response_text

   st.write('要約中...')
   bar = st.progress(0)
   bar.progress(50)

   # 本要約

   # プロンプトテンプレート
   template = """
   We will give you a summary statement of the business-to-business audio.

   Please make a further summary in Markdown format based on all the given summary what was discussed text in 日本語.

   summarize the Summary in the following format.

   # 課題点
   ## h2 headings（複数可）
   - コンテンツ（複数可）
   # 求めること
   ## h2 headings（複数可）
   - コンテンツ（複数可）
   # 提案内容
   ## h2 headings（複数可）
   - コンテンツ（複数可）
   # ネクストアクション
   ## h2 headings（複数可）
   - コンテンツ（複数可）
   # その他
   ## h2 headings（複数可）
   - コンテンツ（複数可）

   use h2 headings and list to make the hierarchical structure.
   Please describe each item in detail.
   Avoid writing the same thing over and over again that means the same thing.
   Since it is known that this is a business meeting, there is no need to include it in the summary.
   """

   # 要約処理（GPT）
   completion = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=[
      {
         "role": "system",
         "content": template
      },
      {
         "role": "user",
         "content": summary
      }
   ])

   # 要約結果
   response_text = completion.choices[0].message.content

   bar.progress(100)

   # マークダウン出力
   st.markdown(response_text)

   # 一時ファイルを削除する
   os.remove(input_path)