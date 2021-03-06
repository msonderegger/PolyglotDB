import os
import re
import librosa
import subprocess
from datetime import datetime
from decimal import Decimal

from influxdb import InfluxDBClient

from ..acoustics import analyze_pitch, analyze_formant_tracks, analyze_intensity, \
    analyze_script, analyze_track_script, analyze_utterance_pitch, update_utterance_pitch_track, analyze_vot
from ..acoustics.classes import Track, TimePoint
from .syllabic import SyllabicContext
from ..acoustics.utils import load_waveform, generate_spectrogram


def sanitize_value(value, type):
    if not isinstance(value, type):
        if isinstance(value, (list, tuple)):
            value = value[0]
        try:
            value = type(value)
        except (ValueError, TypeError):
            value = None
    return value


def generate_filter_string(discourse, begin, end, channel, num_points, kwargs):
    extra_filters = ['''"{}" = '{}' '''.format(k, v) for k, v in kwargs.items()]
    filter_string = '''WHERE "discourse" = '{}'
                            AND "time" >= {}
                            AND "time" <= {}
                            AND "channel" = '{}'
                            '''
    if extra_filters:
        filter_string += '\nAND {}'.format('\nAND '.join(extra_filters))
    if num_points:
        duration = end - begin
        time_step = duration / (num_points - 1)
        begin -= time_step / 2
        end += time_step / 2
        time_step *= 1000
        filter_string += '\ngroup by time({}ms) fill(null)'.format(int(time_step))
    filter_string = filter_string.format(discourse, to_nano(begin), to_nano(end), channel)
    return filter_string


def to_nano(seconds):
    if not isinstance(seconds, Decimal):
        seconds = Decimal(seconds).quantize(Decimal('0.001'))
    return int(seconds * Decimal('1e9'))


def s_to_ms(seconds):
    if not isinstance(seconds, Decimal):
        seconds = Decimal(seconds).quantize(Decimal('0.001'))
    return int(seconds * Decimal('1e3'))


def to_seconds(time_string):
    try:
        d = datetime.strptime(time_string, '%Y-%m-%dT%H:%M:%S.%fZ')
        s = 60 * 60 * d.hour + 60 * d.minute + d.second + d.microsecond / 1e6
    except:
        try:
            d = datetime.strptime(time_string, '%Y-%m-%dT%H:%M:%SZ')
            s = 60 * 60 * d.hour + 60 * d.minute + d.second + d.microsecond / 1e6
        except:
            m = re.search('T(\d{2}):(\d{2}):(\d+)\.(\d+)?', time_string)
            p = m.groups()

            s = 60 * 60 * int(p[0]) + 60 * int(p[1]) + int(p[2]) + int(p[3][:6]) / 1e6

    s = Decimal(s).quantize(Decimal('0.001'))
    return s


class AudioContext(SyllabicContext):
    """
    Class that contains methods for dealing with audio files for corpora
    """

    def load_audio(self, discourse, file_type):
        sound_file = self.discourse_sound_file(discourse)
        if file_type == 'consonant':
            path = os.path.expanduser(sound_file.consonant_file_path)
        elif file_type == 'vowel':
            path = os.path.expanduser(sound_file.vowel_file_path)
        elif file_type == 'low_freq':
            path = os.path.expanduser(sound_file.low_freq_file_path)
        else:
            path = os.path.expanduser(sound_file.file_path)
        signal, sr = librosa.load(path, sr=None)
        return signal, sr

    def load_waveform(self, discourse, file_type='consonant', begin=None, end=None):
        sf = self.discourse_sound_file(discourse)
        if file_type == 'consonant':
            file_path = sf['consonant_file_path']
        elif file_type == 'vowel':
            file_path = sf['vowel_file_path']
        elif file_type == 'low_freq':
            file_path = sf['low_freq_file_path']
        else:
            file_path = sf['file_path']
        return load_waveform(file_path, begin, end)

    def generate_spectrogram(self, discourse, file_type='consonant', begin=None, end=None):
        signal, sr = self.load_waveform(discourse, file_type, begin, end)
        return generate_spectrogram(signal, sr)

    def analyze_pitch(self, source='praat', algorithm='base', stop_check=None, call_back=None, multiprocessing=True):
        analyze_pitch(self, source, algorithm, stop_check, call_back, multiprocessing=multiprocessing)

    def analyze_utterance_pitch(self, utterance, source='praat', **kwargs):
        return analyze_utterance_pitch(self, utterance, source, **kwargs)

    def update_utterance_pitch_track(self, utterance, new_track):
        return update_utterance_pitch_track(self, utterance, new_track)

    def analyze_vot(self,
                    stop_label="stops",
                    stop_check=None,
                    call_back=None,
                    multiprocessing=False,
                    classifier=None,
                    vot_min=5,
                    vot_max=100,
                    window_min=-30,
                    window_max=30):
        analyze_vot(self, stop_label=stop_label, stop_check=stop_check,
                    call_back=call_back, multiprocessing=multiprocessing,
                    vot_min=vot_min, vot_max=vot_max, window_min=window_min,
                    window_max=window_max, classifier=classifier)

    def analyze_formant_tracks(self, source='praat', stop_check=None, call_back=None, multiprocessing=True,
                               vowel_label=None):
        analyze_formant_tracks(self, source=source, stop_check=stop_check, call_back=call_back,
                               multiprocessing=multiprocessing, vowel_label=vowel_label)

    def analyze_intensity(self, source='praat', stop_check=None, call_back=None, multiprocessing=True):
        analyze_intensity(self, source, stop_check, call_back, multiprocessing=multiprocessing)

    def analyze_script(self, phone_class, script_path, duration_threshold=0.01, arguments=None, stop_check=None,
                       call_back=None, multiprocessing=True):
        return analyze_script(self, phone_class, script_path, duration_threshold=duration_threshold,
                              arguments=arguments,
                              stop_check=stop_check, call_back=call_back, multiprocessing=multiprocessing)

    def analyze_track_script(self, acoustic_name, properties, script_path, duration_threshold=0.01,phone_class=None,
                             arguments=None, stop_check=None, call_back=None, multiprocessing=True, file_type='consonant'):
        return analyze_track_script(self, acoustic_name, properties, script_path, duration_threshold=duration_threshold,
                              arguments=arguments, phone_class=phone_class,
                              stop_check=stop_check, call_back=call_back, multiprocessing=multiprocessing, file_type='consonant')

    def reset_formant_points(self):
        encoded_props = []
        for prop in ['F1', 'F2', 'F3', 'B1', 'B2', 'B3', 'A1', 'A2', 'A3']:
            if self.hierarchy.has_token_property('phone', prop):
                encoded_props.append(prop)
        q = self.query_graph(getattr(self, self.phone_name)).set_properties(**{x: None for x in encoded_props})

    def genders(self):
        res = self.execute_cypher(
            '''MATCH (s:Speaker:{corpus_name}) RETURN s.gender as gender'''.format(corpus_name=self.cypher_safe_name))
        genders = set()
        for s in res:
            g = s['gender']
            if g is None:
                g = ''
            genders.add(g)
        return sorted(genders)

    def reset_acoustics(self, call_back=None, stop_check=None):
        self.acoustic_client().drop_database(self.corpus_name)
        if self.hierarchy.acoustics:
            self.hierarchy.acoustic_properties = {}
            self.encode_hierarchy()

    def reset_acoustic_measure(self, acoustic_type):
        self.acoustic_client().query('''DROP MEASUREMENT "{}";'''.format(acoustic_type))
        if acoustic_type in self.hierarchy.acoustics:
            self.hierarchy.acoustic_properties = {k: v for k, v in self.hierarchy.acoustic_properties.items() if
                                                  k != acoustic_type}
            self.encode_hierarchy()

    def reset_vot(self):
        self.execute_cypher('''MATCH (v:vot:{corpus_name}) DETACH DELETE v'''.format(corpus_name=self.cypher_safe_name))
        if 'phone' in self.hierarchy.subannotations:
            if 'vot' in self.hierarchy.subannotations["phone"]:
                self.hierarchy.subannotation_properties.pop("vot")
                self.hierarchy.subannotations["phone"].remove("vot")
                self.encode_hierarchy()

    def acoustic_client(self):
        client = InfluxDBClient(**self.config.acoustic_conncetion_kwargs)
        databases = client.get_list_database()
        if self.corpus_name not in databases:
            client.create_database(self.corpus_name)
        return client

    def discourse_audio_directory(self, discourse):
        """
        Return the directory for the stored audio files for a discourse
        """
        return os.path.join(self.config.audio_dir, discourse)

    def discourse_sound_file(self, discourse):
        statement = '''MATCH (d:Discourse:{corpus_name}) WHERE d.name = {{discourse_name}} return d'''.format(
            corpus_name=self.cypher_safe_name)
        results = self.execute_cypher(statement, discourse_name=discourse).records()
        for r in results:
            d = r['d']
            break
        else:
            raise Exception('Could not find discourse {}'.format(discourse))
        return d

    def utterance_sound_file(self, utterance_id, type='consonant'):
        q = self.query_graph(self.utterance).filter(self.utterance.id == utterance_id).columns(
            self.utterance.begin.column_name('begin'),
            self.utterance.end.column_name('end'),
            self.utterance.discourse.name.column_name('discourse'))
        utterance_info = q.all()[0]
        path = os.path.join(self.discourse_audio_directory(utterance_info['discourse']),
                            '{}_{}.wav'.format(utterance_id, type))
        if os.path.exists(path):
            return path
        fname = self.discourse_sound_file(utterance_info['discourse'])["{}_file_path".format(type)]
        subprocess.call(['sox', fname, path, 'trim', str(utterance_info['begin']),
                         str(utterance_info['end'] - utterance_info['begin'])])
        return path

    def has_all_sound_files(self):
        """
        Check whether all discourses have a sound file

        Returns
        -------
        bool
            True if a sound file exists for each discourse name in corpus,
            False otherwise
        """
        if self._has_all_sound_files is not None:
            return self._has_all_sound_files
        discourses = self.discourses
        for d in discourses:
            sf = self.discourse_sound_file(d)
            if sf is None:
                break
            if not os.path.exists(sf.file_path):
                break
        else:
            self._has_all_sound_files = True
        self._has_all_sound_files = False
        return self._has_all_sound_files

    @property
    def has_sound_files(self):
        """
        Check whether any discourses have a sound file

        Returns
        -------
        bool
            True if there are any sound files at all, false if there aren't
        """

        if self._has_sound_files is None:
            self._has_sound_files = False
            for d in self.discourses:
                sf = self.discourse_sound_file(d)
                if sf['file_path'] is not None:
                    self._has_sound_files = True
                    break
        return self._has_sound_files

    def get_utterance_acoustics(self, acoustic_name, utterance_id, discourse, speaker):
        """
        Get acoustic for a given utterance and time range

        Parameters
        ----------
        acoustic_name : str
            Name of acoustic track
        utterance_id : str
            ID of the utterance from the Neo4j database
        discourse : str
            Name of the discourse
        speaker : str
            Name of the speaker

        Returns
        -------
        :class:`polyglotdb.acoustics.classes.Track`
            Track object
        """
        client = self.acoustic_client()
        properties = [x[0] for x in self.hierarchy.acoustic_properties[acoustic_name]]
        property_names = ["{}".format(x) for x in properties]
        columns = '"time", {}'.format(', '.join(property_names))
        query = '''select {} from "{}"
                        WHERE "utterance_id" = '{}'
                        AND "discourse" = '{}'
                        AND "speaker" = '{}';'''.format(columns, acoustic_name, utterance_id, discourse, speaker)
        result = client.query(query)
        track = Track()
        for r in result.get_points(acoustic_name):
            s = to_seconds(r['time'])
            p = TimePoint(s)
            for name in properties:
                p.add_value(name, r[name])
            track.add(p)
        return track

    def get_acoustic_measure(self, acoustic_name, discourse, begin, end, channel=0, relative_time=False, **kwargs):
        """
        Get acoustic for a given discourse and time range

        Parameters
        ----------
        acoustic_name : str
            Name of acoustic track
        discourse : str
            Name of the discourse
        begin : float
            Beginning of time range
        end : float
            End of time range
        channel : int, defaults to 0
            Channel of the audio file
        relative_time : bool, defaults to False
            Flag for retrieving relative time instead of absolute time
        kwargs : kwargs
            Tags to filter on

        Returns
        -------
        :class:`polyglotdb.acoustics.classes.Track`
            Track object
        """
        begin = Decimal(begin).quantize(Decimal('0.001'))
        end = Decimal(end).quantize(Decimal('0.001'))
        num_points = kwargs.pop('num_points', 0)
        filter_string = generate_filter_string(discourse, begin, end, channel, num_points, kwargs)
        client = self.acoustic_client()

        properties = [x[0] for x in self.hierarchy.acoustic_properties[acoustic_name]]
        property_names = ["{}".format(x) for x in properties]
        if num_points:
            columns = ', '.join(['mean({})'.format(x) for x in property_names])
        else:
            columns = '"time", {}'.format(', '.join(property_names))
        query = '''select {} from "{}"
                        {};'''.format(columns, acoustic_name, filter_string)
        result = client.query(query)
        track = Track()
        for r in result.get_points(acoustic_name):
            s = to_seconds(r['time'])
            if relative_time:
                s = (s - begin) / (end - begin)
            p = TimePoint(s)
            for name in properties:
                p.add_value(name, r[name])
            track.add(p)
        return track

    def _save_measurement_tracks(self, acoustic_name, tracks, speaker):
        data = []

        measures = self.hierarchy.acoustic_properties[acoustic_name]
        for seg, track in tracks.items():
            if not len(track.keys()):
                continue
            file_path, begin, end, channel, utterance_id = seg.file_path, seg.begin, seg.end, seg.channel, seg[
                'utterance_id']
            res = self.execute_cypher(
                'MATCH (d:Discourse:{corpus_name}) where d.low_freq_file_path = {{file_path}} OR '
                'd.vowel_file_path = {{file_path}} OR '
                'd.consonant_file_path = {{file_path}} '
                'RETURN d.name as name'.format(
                    corpus_name=self.cypher_safe_name), file_path=file_path)
            for r in res:
                discourse = r['name']
            phone_type = getattr(self, self.phone_name)
            min_time = min(track.keys())
            max_time = max(track.keys())
            if seg['annotation_type'] == 'phone':
                set_label = seg['label']
            else:
                set_label = None
                q = self.query_graph(phone_type).filter(phone_type.discourse.name == discourse)
                q = q.filter(phone_type.end >= min_time).filter(phone_type.begin <= max_time)
                q = q.columns(phone_type.label.column_name('label'),
                              phone_type.begin.column_name('begin'),
                              phone_type.end.column_name('end')).order_by(phone_type.begin)
                phones = [(x['label'], x['begin'], x['end']) for x in q.all()]
            for time_point, value in track.items():
                fields = {}
                for name, type in measures:
                    v = sanitize_value(value[name], type)
                    if v is not None:
                        fields[name] = v
                if not fields:
                    continue
                if set_label is None:
                    label = None
                    for i, p in enumerate(phones):
                        if p[1] > time_point:
                            break
                        label = p[0]
                        if i == len(phones) - 1:
                            break
                    else:
                        label = None
                else:
                    label = set_label
                if label is None:
                    continue
                t_dict = {'speaker': speaker, 'discourse': discourse, 'channel': channel}
                fields['phone'] = label
                fields['utterance_id'] = utterance_id
                d = {'measurement': acoustic_name,
                     'tags': t_dict,
                     'time': s_to_ms(time_point),
                     'fields': fields
                     }
                data.append(d)
        self.acoustic_client().write_points(data, batch_size=1000, time_precision='ms')

    def _save_measurement(self, sound_file, track, acoustic_name, **kwargs):
        if not len(track.keys()):
            return
        if isinstance(sound_file, str):
            sound_file = self.discourse_sound_file(sound_file)
        if sound_file is None:
            return
        measures = self.hierarchy.acoustic_properties[acoustic_name]
        if kwargs.get('channel', None) is None:
            kwargs['channel'] = 0
        data = []
        tag_dict = {}
        if isinstance(sound_file, str):
            kwargs['discourse'] = sound_file
        else:
            kwargs['discourse'] = sound_file['name']
        utterance_id = kwargs.pop('utterance_id', None)
        tag_dict.update(kwargs)
        phone_type = getattr(self, self.phone_name)
        min_time = min(track.keys())
        max_time = max(track.keys())
        q = self.query_graph(phone_type).filter(phone_type.discourse.name == kwargs['discourse'])
        q = q.filter(phone_type.end >= min_time).filter(phone_type.begin <= max_time)
        q = q.columns(phone_type.label.column_name('label'),
                      phone_type.begin.column_name('begin'),
                      phone_type.end.column_name('end'),
                      phone_type.speaker.name.column_name('speaker')).order_by(phone_type.begin)
        phones = [(x['label'], x['begin'], x['end'], x['speaker']) for x in q.all()]
        for time_point, value in track.items():
            fields = {}
            for name, type in measures:
                v = sanitize_value(value[name], type)
                if v is not None:
                    fields[name] = v
            if not fields:
                continue
            label = None
            speaker = None
            for i, p in enumerate(phones):
                if p[1] > time_point:
                    break
                label = p[0]
                speaker = p[-1]
                if i == len(phones) - 1:
                    break
            else:
                label = None
                speaker = None
            if speaker is None:
                continue
            t_dict = {'speaker': speaker}
            t_dict.update(tag_dict)
            if utterance_id is not None:
                fields['utterance_id'] = utterance_id
            fields['phone'] = label
            d = {'measurement': acoustic_name,
                 'tags': t_dict,
                 'time': to_nano(time_point),
                 'fields': fields
                 }
            data.append(d)
        self.acoustic_client().write_points(data, batch_size=1000)

    def save_acoustic_track(self, acoustic_name, discourse, track, **kwargs):
        """
        Save an acoustic track for a sound file

        Parameters
        ----------
        acoustic_name : str
            Name of the acoustic type
        discourse : str
            Name of the discourse
        track : :class:`polyglotdb.acoustics.classes.Track`
            Dictionary with times as keys and tuples of F1, F2, and F3 values as values
        kwargs: kwargs
            Tags to save for acoustic measurements
        """
        self._save_measurement(discourse, track, acoustic_name, **kwargs)

    def save_acoustic_tracks(self, acoustic_name, tracks, speaker):
        """
        Save multiple acoustic tracks for a collection of analyzed segments

        Parameters
        ----------
        acoustic_name : str
            Name of the acoustic type
        speaker : str
            Name of the speaker of the tracks
        tracks : dict
            Dictionary with times as keys and tuples of F1, F2, and F3 values as values
        """
        self._save_measurement_tracks(acoustic_name, tracks, speaker)

    def discourse_has_acoustics(self, acoustic_name, discourse):
        """
        Return whether a discourse has any specific acoustic values associated with it

        Parameters
        ----------
        acoustic_name : str
            Name of the acoustic type
        discourse : str
            Name of the discourse

        Returns
        -------
        bool
        """
        if acoustic_name not in self.hierarchy.acoustics:
            return False
        client = self.acoustic_client()
        query = '''select * from "{}" WHERE "discourse" = '{}' LIMIT 1;'''.format(acoustic_name, discourse)
        result = client.query(query)
        if len(result) == 0:
            return False
        return True

    def encode_acoustic_statistic(self, acoustic_name, statistic, by_phone=True, by_speaker=False):
        """
        Computes and saves as type properties summary statistics on a by speaker or by phone basis (or both) for a
        given acoustic measure.


        Parameters
        ----------
        acoustic_name : str
            Name of the acoustic type
        statistic : str
            One of `mean`, `median`, `stddev`, `sum`, `mode`, `count`
        by_speaker : bool, defaults to True
            Flag for calculating summary statistic by speaker
        by_phone : bool, defaults to False
            Flag for calculating summary statistic by phone


        """
        if not by_speaker and not by_phone:
            raise (Exception('Please specify either by_phone, by_speaker or both.'))
        if acoustic_name not in self.hierarchy.acoustics:
            raise (ValueError('Acoustic measure must be one of: {}.'.format(', '.join(self.hierarchy.acoustics))))
        available_statistics = ['mean', 'median', 'stddev', 'sum', 'mode', 'count']
        if statistic not in available_statistics:
            raise ValueError('Statistic name should be one of: {}.'.format(', '.join(available_statistics)))

        client = self.acoustic_client()
        acoustic_name = acoustic_name.lower()
        template = statistic + '("{0}") as "{0}"'
        statistic_template = 'n.{statistic}_{measure} = d.{measure}'
        measures = {x[0]: template.format(x[0]) for x in self.hierarchy.acoustic_properties[acoustic_name] if
                    x[1] in [int, float]}
        if by_speaker and by_phone:
            results = []
            for p in self.phones:
                query = '''select {} from "{}"
                                where "phone" = '{}' group by "speaker";'''.format(
                    ', '.join(measures), acoustic_name, p)

                influx_result = client.query(query)
                for k, v in influx_result.items():
                    result = {'speaker': k[1]['speaker'], 'phone': p}
                    for measure in measures.keys():
                        result[measure] = list(v)[0][measure]
                    results.append(result)

            set_statements = []
            for measure in measures.keys():
                set_statements.append(statistic_template.format(statistic=statistic, measure=measure))
            statement = '''WITH {{data}} as data
                        UNWIND data as d
                        MATCH (s:Speaker:{corpus_name}), (p:phone_type:{corpus_name})
                        WHERE p.label = d.phone AND s.name = d.speaker
                        WITH p, s, d
                        MERGE (s)<-[n:spoken_by]-(p)
                        WITH n, d
                        SET {set_statements}'''.format(corpus_name=self.cypher_safe_name,
                                                       set_statements='\nAND '.join(set_statements))
        elif by_phone:
            results = []
            for p in self.phones:
                query = '''select {} from "{}"
                                where "phone" = '{}';'''.format(', '.join(measures.values()),
                                                                acoustic_name, p)

                influx_result = client.query(query)
                result = {'phone': p}
                for k, v in influx_result.items():
                    for measure in measures.keys():
                        result[measure] = list(v)[0][measure]
                results.append(result)
            set_statements = []
            for measure in measures.keys():
                set_statements.append(statistic_template.format(statistic=statistic, measure=measure))
            statement = '''WITH {{data}} as data
                                UNWIND data as d
                                MATCH (n:phone_type:{corpus_name})
                                WHERE n.label = d.phone
                                SET {set_statements}'''.format(corpus_name=self.cypher_safe_name,
                                                               set_statements='\nAND '.join(set_statements))
            self.hierarchy.add_type_properties(self, 'phone',
                                               [('{}_{}'.format(statistic, x), float) for x in measures.keys()])
        elif by_speaker:
            query = '''select {} from "{}" group by "speaker";'''.format(', '.join(measures), acoustic_name)
            influx_result = client.query(query)
            results = []

            for k, v in influx_result.items():
                result = {'speaker': k[1]['speaker']}
                for measure in measures.keys():
                    result[measure] = list(v)[0][measure]
                results.append(result)

            set_statements = []
            for measure in measures.keys():
                set_statements.append(statistic_template.format(statistic=statistic, measure=measure))
            statement = '''WITH {{data}} as data
                            UNWIND data as d
                            MATCH (n:Speaker:{corpus_name})
                            WHERE n.name = d.speaker
                            SET {set_statements}'''.format(corpus_name=self.cypher_safe_name,
                                                           set_statements='\nAND '.join(set_statements))
            self.hierarchy.add_speaker_properties(self,
                                                  [('{}_{}'.format(statistic, x), float) for x in measures.keys()])
        self.execute_cypher(statement, data=results)
        self.encode_hierarchy()

    def get_acoustic_statistic(self, acoustic_name, statistic, by_phone=True, by_speaker=False):
        """
        Computes summary statistics on a by speaker or by phone basis (or both) for a given acoustic measure.


        Parameters
        ----------
        acoustic_name : str
            Name of the acoustic type
        statistic : str
            One of `mean`, `median`, `stddev`, `sum`, `mode`, `count`
        by_speaker : bool, defaults to True
            Flag for calculating summary statistic by speaker
        by_phone : bool, defaults to False
            Flag for calculating summary statistic by phone

        Returns
        -------
        dict
            Dictionary where keys are phone/speaker/phone-speaker pairs and values are the summary statistic
            of the acoustic measure

        """
        if acoustic_name not in self.hierarchy.acoustics:
            raise (ValueError('Acoustic measure must be one of: {}.'.format(', '.join(self.hierarchy.acoustics))))
        if not by_speaker and not by_phone:
            raise (Exception('Please specify either by_phone, by_speaker or both.'))
        available_statistics = ['mean', 'median', 'stddev', 'sum', 'mode', 'count']
        if statistic not in available_statistics:
            raise ValueError('Statistic name should be one of: {}.'.format(', '.join(available_statistics)))

        prop_template = 'n.{0} as {0}'

        measures = ['{}_{}'.format(statistic, x[0]) for x in self.hierarchy.acoustic_properties[acoustic_name] if
                    x[1] in [int, float]]
        returns = [prop_template.format(x) for x in measures]

        if by_phone and by_speaker:
            statement = '''MATCH (p:phone_type:{corpus_name})-[n:spoken_by]->(s:Speaker:{corpus_name}) 
            return {return_list} LIMIT 1'''.format(corpus_name=self.cypher_safe_name, return_list=', '.join(returns))
            results = self.execute_cypher(statement).records()
            try:
                first = next(results)
            except StopIteration:
                first = None
            if first is None:
                self.encode_acoustic_statistic(acoustic_name, statistic, by_phone, by_speaker)
            statement = '''MATCH (p:phone_type:{corpus_name})-[n:spoken_by]->(s:Speaker:{corpus_name})
            return p.label as phone, s.name as speaker, {return_list}'''.format(
                corpus_name=self.cypher_safe_name, return_list=', '.join(returns))
            results = self.execute_cypher(statement).records()
            results = {(x['speaker'], x['phone']): [x[n] for n in measures] for x in results}

        elif by_phone:
            if not self.hierarchy.has_type_property('phone', measures[0]):
                self.encode_acoustic_statistic(acoustic_name, statistic, by_phone, by_speaker)
            statement = '''MATCH (n:phone_type:{corpus_name})
            return n.label as phone, {return_list}'''.format(
                corpus_name=self.cypher_safe_name, return_list=', '.join(returns))
            results = self.execute_cypher(statement).records()
            results = {x['phone']: [x[n] for n in measures] for x in results}
        elif by_speaker:
            if not self.hierarchy.has_speaker_property(measures[0]):
                self.encode_acoustic_statistic(acoustic_name, statistic, by_phone, by_speaker)
            statement = '''MATCH (n:Speaker:{corpus_name})
            return n.name as speaker, {return_list}'''.format(
                corpus_name=self.cypher_safe_name, return_list=', '.join(returns))
            results = self.execute_cypher(statement).records()
            results = {x['speaker']: [x[n] for n in measures] for x in results}
        return results

    def reset_relativized_acoustic_measure(self, acoustic_name):
        """
        Reset any relativized measures that have been encoded for a specified type of acoustics

        Parameters
        ----------
        acoustic_name : str
            Name of the acoustic type

        """
        if acoustic_name not in self.hierarchy.acoustics:
            raise (ValueError('Acoustic measure must be one of: {}.'.format(', '.join(self.hierarchy.acoustics))))
        measures = ', '.join(
            ['"{}"'.format(x[0]) for x in self.hierarchy.acoustic_properties[acoustic_name] if x[1] in [int, float]
             and not x[0].endswith('relativized')])
        to_remove = [x[0] for x in self.hierarchy.acoustic_properties[acoustic_name] if x[0].endswith('relativized')]
        client = self.acoustic_client()
        query = """SELECT "phone", {measures}, "utterance_id" 
        INTO "{name}_copy" FROM "{name}" GROUP BY *;""".format(name=acoustic_name, measures=measures)
        client.query(query)
        client.query('DROP MEASUREMENT "{}"'.format(acoustic_name))
        client.query('SELECT * INTO "{0}" FROM "{0}_copy" GROUP BY *'.format(acoustic_name))
        client.query('DROP MEASUREMENT "{}_copy"'.format(acoustic_name))
        self.hierarchy.remove_acoustic_properties(self, acoustic_name, to_remove)
        self.encode_hierarchy()

    def relativize_acoustic_measure(self, acoustic_name, by_speaker=True, by_phone=False):
        """
        Relativize acoustic tracks by taking the z-score of the points (using by speaker or by phone means and standard
        deviations, or both by-speaker, by phone) and save them as separate measures, i.e., F0_relativized from F0.

        Parameters
        ----------
        acoustic_name : str
            Name of the acoustic measure
        by_speaker : bool, defaults to True
            Flag for relativizing by speaker
        by_phone : bool, defaults to False
            Flag for relativizing by phone
        """
        if acoustic_name not in self.hierarchy.acoustics:
            raise (ValueError('Acoustic measure must be one of: {}.'.format(', '.join(self.hierarchy.acoustics))))
        if not by_speaker and not by_phone:
            raise Exception('Relativization must be by phone, speaker, or both.')
        client = self.acoustic_client()
        phone_type = getattr(self, self.phone_name)
        template = 'mean("{0}") as mean_{0}, stddev("{0}") as sd_{0}'
        summary_data = {}
        props = [x for x in self.hierarchy.acoustic_properties[acoustic_name] if
                      x[1] in [int, float] and not x[0].endswith('relativized')]
        statistics = {x[0]: template.format(x[0]) for x in props}
        aliases = {x[0]: ('mean_' + x[0], 'sd_' + x[0]) for x in props}
        if by_phone:
            for p in self.phones:
                if by_speaker:
                    query = '''select {statistics} from "{acoustic_type}" 
                    where "phone" = '{phone}' group by "speaker";'''.format(acoustic_type=acoustic_name,
                                                                            statistics=', '.join(statistics.values()),
                                                                            phone=p)
                    result = client.query(query)
                    for k, v in result.items():
                        v = list(v)
                        for measure, (mean_name, sd_name) in aliases.items():
                            summary_data[(k[1]['speaker'], p, measure)] = v[0][mean_name], v[0][sd_name]

                else:
                    query = '''select {statistics} from "{acoustic_type}" 
                    where "phone" = '{phone}';'''.format(acoustic_type=acoustic_name,
                                                         statistics=', '.join(statistics.values()), phone=p)
                    result = client.query(query)
                    for k, v in result.items():
                        v = list(v)
                        for measure, (mean_name, sd_name) in aliases.items():
                            summary_data[(p, measure)] = v[0][mean_name], v[0][sd_name]
        else:
            query = '''select {statistics} from "{acoustic_type}" 
            where "phone" != '' group by "speaker";'''.format(acoustic_type=acoustic_name,
                                                              statistics=', '.join(statistics.values()))
            result = client.query(query)
            for k, v in result.items():
                v = list(v)
                for measure, (mean_name, sd_name) in aliases.items():
                    summary_data[(k[1]['speaker'], measure)] = v[0][mean_name], v[0][sd_name]
        for s in self.speakers:
            all_query = '''select * from "{acoustic_type}"
            where "phone" != '' and "speaker" = '{speaker}';'''.format(acoustic_type=acoustic_name, speaker=s)
            all_results = client.query(all_query)
            data = []
            for _, r in all_results.items():
                for t_dict in r:
                    phone = t_dict.pop('phone')
                    utterance_id = t_dict.pop('utterance_id', '')
                    time_point = t_dict.pop('time')
                    fields = {}
                    for measure, (mean_name, sd_name) in aliases.items():
                        if by_speaker and by_phone:
                            mean_value, sd_value = summary_data[(t_dict['speaker'], phone, measure)]
                        elif by_phone and not by_speaker:
                            mean_value, sd_value = summary_data[(phone, measure)]
                        elif by_speaker:
                            mean_value, sd_value = summary_data[(t_dict['speaker'], measure)]
                        if sd_value is None:
                            continue
                        value = t_dict.pop(measure)
                        if value is None:
                            continue
                        new_value = t_dict.pop('{}_relativized'.format(measure), None)
                        new_value= (value - mean_value) / sd_value
                        fields['{}_relativized'.format(measure)] = new_value
                    if not fields:
                        continue
                    time_point = s_to_ms(to_seconds(time_point))
                    d = {'measurement': acoustic_name,
                         'tags': t_dict,
                         "time": time_point,
                         "fields": fields
                         }
                    data.append(d)
            client.write_points(data, batch_size=1000, time_precision='ms')
        self.hierarchy.add_acoustic_properties(self, acoustic_name, [(x[0] +'_relativized', float) for x in props])
        self.encode_hierarchy()

    def reassess_utterances(self, acoustic_name):
        """
        Update utterance IDs in InfluxDB for more efficient querying if utterances have been re-encoded after acoustic
        measures were encoded

        Parameters
        ----------
        acoustic_name : str
            Name of the measure for which to update utterance IDs

        """
        if acoustic_name not in self.hierarchy.acoustics:
            raise (ValueError('Acoustic measure must be one of: {}.'.format(', '.join(self.hierarchy.acoustics))))
        client = self.acoustic_client()
        q = self.query_discourses()
        q = q.columns(self.discourse.name.column_name('name'),
                      self.discourse.speakers.name.column_name('speakers'))
        discourses = q.all()
        props = [x[0] for x in self.hierarchy.acoustic_properties[acoustic_name]]
        for d in discourses:
            discourse_name = d['name']
            data = []
            for s in d['speakers']:
                q = self.query_graph(self.utterance)
                q = q.filter(self.utterance.discourse.name == discourse_name, self.utterance.speaker.name == s)
                q = q.order_by(self.utterance.begin)
                q = q.columns(self.utterance.id.column_name('utterance_id'),
                              self.utterance.begin.column_name('begin'),
                              self.utterance.end.column_name('end'))
                utterances = q.all()
                all_query = '''select * from "{}"
                                where "phone" != '' and 
                                "discourse" = '{}' and 
                                "speaker" = '{}';'''.format(acoustic_name, discourse_name, s)
                all_results = client.query(all_query)
                cur_index = 0
                for _, r in all_results.items():
                    for t_dict in r:
                        phone = t_dict.pop('phone')
                        utterance_id = t_dict.pop('utterance_id', '')
                        for m in props:
                            value = t_dict.pop(m, None)

                        time_point = to_seconds(t_dict.pop('time'))
                        for i in range(cur_index, len(utterances)):
                            if utterances[i]['begin'] <= time_point <= utterances[i]['end']:
                                cur_index = i
                                break
                        time_point = s_to_ms(time_point)
                        d = {'measurement': acoustic_name,
                             'tags': t_dict,
                             "time": time_point,
                             "fields": {'utterance_id': utterances[cur_index]['utterance_id']}
                             }
                        data.append(d)
            client.write_points(data, batch_size=1000, time_precision='ms')
