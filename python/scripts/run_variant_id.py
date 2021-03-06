import os
import sys
import math
import plotly.offline as py
import pandas
from Bio import pairwise2
from varcode import Variant
from pyensembl import ensembl_grch38   # pyensembl install --release 95 --species homo_sapiens


def main():

    # Consequence configuration
    consequence_config = pandas.read_csv(os.path.join(os.path.dirname(os.path.realpath(__file__)), 'consequence.csv'))

    consequences = consequence_config[['name', 'weight']].copy()
    CONSEQUENCE_WEIGHTING = consequences.set_index('name').transpose().to_dict('records')[0]

    categories = consequence_config[['name', 'category']].copy()
    CONSEQUENCE_CATEGORIES = categories.set_index('name').transpose().to_dict('records')[0]

    impact = consequence_config[['category', 'weight']].copy()
    impact.drop_duplicates(inplace=True)
    IMPACT_WEIGHTING = impact.set_index('category').transpose().to_dict('records')[0]

    # Output folder name for plots and data
    folder_name = 'editid_variantid'
    if not os.path.exists(folder_name):
        os.mkdir(folder_name)

    # Checking two input/output files from amplicount exist
    if (not os.path.exists('amplicount.csv')) or (not os.path.exists('amplicount_config.csv')):
        print('Input files amplicount_config.csv, or amplicount.csv not found, please run amplicount tool first.')
        sys.exit(1)

    # Load amplicount files (configuration and variants) into pandas dataframe for analysis and ploting
    df_config = pandas.read_csv('amplicount_config.csv')
    df_variants = pandas.read_csv('amplicount.csv')

    # Filter out low-frequency variants
    df_variants = df_variants[(df_variants['variant_frequency'] > 5)]

    # List of samples
    samples = df_variants[['sample_id']].copy()
    samples.drop_duplicates(inplace=True)
    samples.reset_index(inplace=True)

    # List of amplicons
    amplicons = df_variants[['amplicon_id']].copy()
    amplicons.drop_duplicates(inplace=True)
    amplicons.reset_index(inplace=True)

    # List of variants
    variants = df_variants[['amplicon_id', 'sequence']].copy()
    variants.drop_duplicates(inplace=True)
    variants.reset_index(inplace=True)


    # Get variant classification using https://github.com/openvax/varcode and https://github.com/openvax/pyensembl
    def get_variant_classification(contig, start, ref, alt, genome=ensembl_grch38):
        try:
            var = Variant(contig=contig, start=start, ref=ref, alt=alt, ensembl=genome)
            top_effect = var.effects().top_priority_effect()
            consequence = top_effect.__class__.__name__
            weight = CONSEQUENCE_WEIGHTING.get(consequence, 0)
        except Exception:
            consequence = 'Unclassified'
            weight = 0
        finally:
            if len(ref) > len(alt):
                return 'Deletion', consequence, weight
            elif len(ref) < len(alt):
                return 'Insertion', consequence, weight
            else:
                return 'Mismatch', consequence, weight


    # Calculate KO score
    def calculate_score(row):
        score = 0
        for name in IMPACT_WEIGHTING.keys():
            score += row[name]*IMPACT_WEIGHTING[name]
        return score/100

    # Pairwise alignment to classify variant
    with open(os.path.join(folder_name, 'variantid.out'), 'w') as out:
        for i, variant in variants.iterrows():
            # get reference sequence
            amplicon_id = variant['amplicon_id']
            df_ref_sequence = df_config[(df_config['id'] == amplicon_id)]
            ref_sequence = df_ref_sequence.iloc[0]['amplicon']
            variant_id = 'var{}'.format(i + 1)
            data = []
            top_effect_types = set()
            top_effect_consequences = set()
            top_effect_scores = []
            if variant['sequence'] == ref_sequence:
                type = 'WildType'
                top_effect_types.add(type)
                top_effect_consequences.add(type)
                top_effect_scores.append(0)
                coord = df_config[(df_config['id'] == amplicon_id)].iloc[0]['coord']
                out.write(">{}_{}_{}_{}\n{}\n".format(amplicon_id, variant_id, type, coord, ref_sequence))
            else:
                alignments = pairwise2.align.globalms(ref_sequence, variant['sequence'], 5, -4, -3, -0.1)
                ibase_start = 0
                ibase_stop = 0
                variant_results = []
                for ibase in range(1, len(alignments[0][0])-1):
                    chr, ref_start = amplicon_id.split('_')
                    contig = chr[3:]
                    top_effect_consequence = ''
                    top_effect_type = ''
                    # looking for mismatch
                    if not alignments[0][0][ibase] == alignments[0][1][ibase]:
                        if not alignments[0][0][ibase] == '-' and not alignments[0][1][ibase] == '-':
                            start = int(ref_start)+ibase
                            ref = "{}".format(alignments[0][0][ibase])
                            alt = "{}".format(alignments[0][1][ibase])
                            top_effect_type, top_effect_consequence, score = get_variant_classification(contig, start, ref, alt)
                            variant_results.append('{}\t{}\t{}\t{}\t{}'.format(contig, start, ref, alt, top_effect_consequence))
                            top_effect_types.add(top_effect_type)
                            top_effect_consequences.add(top_effect_consequence)
                            top_effect_scores.append(score)
                    # looking for insertion and deletion
                    if alignments[0][0][ibase] == '-' or alignments[0][1][ibase] == '-':
                        if not alignments[0][0][ibase-1] == '-' and not alignments[0][1][ibase-1] == '-':
                            ibase_start = ibase - 1
                    if ibase_start:
                        if not alignments[0][0][ibase+1] == '-' and not alignments[0][1][ibase+1] == '-':
                            ibase_stop = ibase + 1
                    if ibase_start and ibase_stop:
                        start = int(ref_start)+ibase_start
                        ref = "{}".format(alignments[0][0][ibase_start:ibase_stop].replace('-', ''))
                        alt = "{}".format(alignments[0][1][ibase_start:ibase_stop].replace('-', ''))
                        top_effect_type, top_effect_consequence, score = get_variant_classification(contig, start, ref, alt)
                        variant_results.append('{}\t{}\t{}\t{}\t{}'.format(contig, start, ref, alt, top_effect_consequence))
                        top_effect_types.add(top_effect_type)
                        top_effect_consequences.add(top_effect_consequence)
                        top_effect_scores.append(score)
                        ibase_start = 0
                        ibase_stop = 0
            if len(top_effect_consequences) > 1:
                if 'FrameShift' in top_effect_consequences:
                    top_effect_consequence = 'ComplexFrameShift'
                    score = CONSEQUENCE_WEIGHTING.get(top_effect_consequence, 0)
                else:
                    top_effect_consequence = 'Complex'
                    score = CONSEQUENCE_WEIGHTING.get(top_effect_consequence, 0)
            else:
                top_effect_consequence = ''.join(top_effect_consequences)
                score = top_effect_scores[0]
            name = '{}_{}'.format(variant_id, ','.join(top_effect_consequences))
            out.write(">{}_{}\n{}\n".format(amplicon_id, name, variant['sequence']))
            out.write(pairwise2.format_alignment(*alignments[0]))
            out.write('CHROM\tPOS\tREF\tALT\tTOP_EFFECT\n')
            out.write('{}\n'.format('\n'.join(variant_results)))
            df_variants.loc[((df_variants['amplicon_id'] == amplicon_id) & (df_variants['sequence'] == variant['sequence'])), 'variant_id'] = variant_id
            df_variants.loc[((df_variants['amplicon_id'] == amplicon_id) & (df_variants['sequence'] == variant['sequence'])), 'variant_type'] = '_'.join(top_effect_types)
            df_variants.loc[((df_variants['amplicon_id'] == amplicon_id) & (df_variants['sequence'] == variant['sequence'])), 'variant_consequence'] = top_effect_consequence
            df_variants.loc[((df_variants['amplicon_id'] == amplicon_id) & (df_variants['sequence'] == variant['sequence'])), 'variant_score'] = score*df_variants['variant_frequency']
            out.write('\n')

    df_variants.drop_duplicates(inplace=True)
    df_variants.to_csv(os.path.join(folder_name, 'variantid.csv'), index=False)

    # Amplicon Read Coverage plots
    df_amplicons = df_variants[['sample_id', 'amplicon_id', 'amplicon_reads', 'amplicon_filtered_reads', 'amplicon_low_quality_reads', 'amplicon_primer_dimer_reads', 'amplicon_low_abundance_reads']].copy()
    df_amplicons.drop_duplicates(inplace=True)

    COLORS = {
        'amplicon_filtered_reads': 'rgb(12,100,201)',
        'amplicon_low_quality_reads': 'rgb(204,204,204)',
        'amplicon_primer_dimer_reads': 'rgb(170,170,170)',
        'amplicon_low_abundance_reads': 'rgb(133,133,133)'
    }
    MAX_READS = df_amplicons.loc[df_amplicons['amplicon_reads'].idxmax()]['amplicon_reads']

    for i, amplicon in amplicons.iterrows():
        df_coverage = df_amplicons[df_amplicons['amplicon_id'] == amplicon['amplicon_id']].copy()
        df_coverage.sort_values(by=['amplicon_filtered_reads'], inplace=True)
        print('Creating Amplicon Read Coverage plot for {}'.format(amplicon['amplicon_id']))
        data = []
        for name in ['amplicon_filtered_reads', 'amplicon_low_quality_reads', 'amplicon_primer_dimer_reads', 'amplicon_low_abundance_reads']:
            trace = {
                'x': df_coverage[name],
                'y': df_coverage['sample_id'],
                'name': ' '.join(name.split('_')[1:]),
                'type': 'bar',
                'orientation': 'h',
                'marker': {
                    'color': COLORS[name]
                }
            }
            data.append(trace)

        layout = {'barmode': 'stack',
                  'title': 'Amplicon Read Coverage for {}'.format(amplicon['amplicon_id']),
                  #'xaxis': {'title': 'number of reads'},  # for project GEP00005
                  'xaxis': {'title': 'number of reads', 'type': 'log', 'range': [0, math.log10(MAX_READS)]},
                  'yaxis': {'title': 'samples'}}

        py.plot({'data': data, 'layout': layout}, filename=os.path.join(folder_name, 'coverage_{}.html'.format(amplicon['amplicon_id'])), auto_open=False)

    # Variant fraction plots
    VCOLORS = {
        'HighImpact': 'rgb(174,19,36)',
        'MediumImpact': 'rgb(206,123,18)',
        'LowImpact': 'rgb(233,185,28)',
        'WildType': 'rgb(250,253,225)',
        'LowFrequency': 'rgb(238,238,238)'
    }
    for consequence in CONSEQUENCE_CATEGORIES.keys():
        df_variants.loc[(df_variants['variant_consequence'] == consequence), 'impact'] = CONSEQUENCE_CATEGORIES[consequence]
    df_variants.loc[(df_variants['variant_consequence'] != 'WildType') & (df_variants['variant_score'] == 0), 'impact'] = 'LowImpact'
    df_impacts = df_variants[['sample_id', 'amplicon_id', 'impact', 'variant_frequency']].copy()
    grouped_impacts = df_impacts.groupby(['sample_id', 'amplicon_id', 'impact'])
    df_impacts['impact_frequency'] = grouped_impacts.transform('sum')
    df_impacts = df_impacts.loc[:, ['sample_id', 'amplicon_id', 'impact', 'impact_frequency']]
    df_impacts.drop_duplicates(inplace=True)
    df_impacts.to_csv(os.path.join(folder_name, 'impacts.csv'), index=False)
    for i, amplicon in amplicons.iterrows():
        data = []
        df_impacts_per_amplicon = df_impacts[df_impacts['amplicon_id'] == amplicon['amplicon_id']]
        pivot_df_impacts_per_amplicon = df_impacts_per_amplicon.pivot(index='sample_id', columns='impact', values='impact_frequency').reset_index()
        pivot_df_impacts_per_amplicon.fillna(value=0, inplace=True)
        pivot_df_impacts_per_amplicon['LowFrequency'] = 100 - pivot_df_impacts_per_amplicon.iloc[:, 1:].sum(axis=1)
        for name in IMPACT_WEIGHTING.keys():
            if name not in pivot_df_impacts_per_amplicon.columns:
                pivot_df_impacts_per_amplicon[name] = 0
        pivot_df_impacts_per_amplicon['koscore'] = pivot_df_impacts_per_amplicon.apply(calculate_score, axis=1)
        pivot_df_impacts_per_amplicon.sort_values(by=['koscore'], ascending=[True], inplace=True)
        pivot_df_impacts_per_amplicon.to_csv(os.path.join(folder_name, 'koscores_{}.csv'.format(amplicon['amplicon_id'])), index=False)
        for name in ['HighImpact', 'MediumImpact', 'LowImpact', 'WildType', 'LowFrequency']:
            trace = {
                'x': pivot_df_impacts_per_amplicon[name],
                'y': pivot_df_impacts_per_amplicon['sample_id'],
                'name': name,
                'type': 'bar',
                'orientation': 'h',
                'marker': {
                    'color': VCOLORS[name]
                }
            }
            data.append(trace)
        layout = {'barmode': 'stack',
                  'title': 'Variant Impact Frequency for {}'.format(amplicon['amplicon_id']),
                  'xaxis': {'title': 'frequency'},
                  'yaxis': {'title': 'samples'}}

        py.plot({'data': data, 'layout': layout}, filename=os.path.join(folder_name, 'koscores_{}.html'.format(amplicon['amplicon_id'])), auto_open=False)


if __name__ == '__main__':
    main()
